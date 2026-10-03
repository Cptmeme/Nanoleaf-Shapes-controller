#pragma once
/*
 * Panel colours from the WLED matrix: every panel takes all the cells under it, weighted by how much of each cell
 * it covers, rather than the one cell at its centre.
 *
 * The weight table is built once per layout or setting change; sample() uses integer arithmetic only.
 * Plain C++ without Arduino dependencies, so it can be tested on a host.
 */
#include <vector>
#include "leafbus_geometry.h"

namespace leafbus {

constexpr int SUBSAMPLES = 4;  // per cell side when measuring how much of a cell a panel covers

struct WeightEntry {
  uint16_t cell;   // row * width + column
  uint8_t  weight; // 1..255; the largest weight of every panel is 255
};

struct PanelWeights {
  uint16_t first;  // first entry
  uint16_t count;
};

struct WeightTable {
  uint8_t width = 0, height = 0;
  std::vector<WeightEntry> entries;
  std::vector<PanelWeights> panels;  // by layout position
};

namespace detail {

// Corners of a placed panel in mm, after the layout rotation. Returns 3 or 6.
inline int outline(const Panel &p, float rotationDeg, float *xs, float *ys) {
  int n;
  float radius, start, stepDeg;
  if (p.shape == SHAPE_HEXAGON) {
    n = 6; radius = 67.0f; start = 0.0f; stepDeg = 60.0f;
  } else {  // a triangle; an unknown shape counts as a Mini Triangle
    n = 3; radius = (p.shape == SHAPE_TRIANGLE ? 134.0f : 67.0f) / 1.7320508f; start = -30.0f; stepDeg = 120.0f;
  }
  for (int k = 0; k < n; k++) {
    float vx, vy;
    rotate(radius, 0.0f, start + stepDeg * k + p.o, vx, vy);
    rotate(p.x + vx, p.y + vy, rotationDeg, xs[k], ys[k]);
  }
  return n;
}

inline bool insidePolygon(const float *xs, const float *ys, int n, float px, float py) {
  bool neg = false, pos = false;
  for (int i = 0; i < n; i++) {
    int j = (i + 1) % n;
    float cross = (xs[j] - xs[i]) * (py - ys[i]) - (ys[j] - ys[i]) * (px - xs[i]);
    if (cross < -1e-3f) neg = true;
    if (cross > 1e-3f) pos = true;
  }
  return !(neg && pos);
}

}  // namespace detail

// Weight of every cell for every panel: the share of SUBSAMPLES² points in the cell that lie inside the panel,
// scaled so each panel's largest weight is 255.
inline void buildWeights(const Panel *p, int n, float rotationDeg, uint8_t width, uint8_t height,
                         const GridTransform &xf, WeightTable &t) {
  t.width = width;
  t.height = height;
  t.entries.clear();
  t.panels.assign(n, PanelWeights{0, 0});
  std::vector<int> hits;

  for (int i = 0; i < n; i++) {
    float xs[6], ys[6];
    int k = detail::outline(p[i], rotationDeg, xs, ys);
    float lo = 1e9f, hi = -1e9f, bottom = 1e9f, top = -1e9f;
    for (int j = 0; j < k; j++) {
      lo = fminf(lo, xs[j]); hi = fmaxf(hi, xs[j]);
      bottom = fminf(bottom, ys[j]); top = fmaxf(top, ys[j]);
    }
    int c0 = (int)floorf((lo - xf.minX) / xf.stepX), c1 = (int)ceilf((hi - xf.minX) / xf.stepX);
    int r0 = (int)floorf((xf.maxY - top) / xf.stepY), r1 = (int)ceilf((xf.maxY - bottom) / xf.stepY);
    if (c0 < 0) c0 = 0;
    if (r0 < 0) r0 = 0;
    if (c1 > width - 1) c1 = width - 1;
    if (r1 > height - 1) r1 = height - 1;

    size_t first = t.entries.size();
    hits.clear();
    int best = 0;
    for (int row = r0; row <= r1; row++)
      for (int col = c0; col <= c1; col++) {
        float cx = xf.minX + col * xf.stepX, cy = xf.maxY - row * xf.stepY;
        int in = 0;
        for (int sy = 0; sy < SUBSAMPLES; sy++)
          for (int sx = 0; sx < SUBSAMPLES; sx++) {
            float px = cx + ((sx + 0.5f) / SUBSAMPLES - 0.5f) * xf.stepX;
            float py = cy - ((sy + 0.5f) / SUBSAMPLES - 0.5f) * xf.stepY;
            if (detail::insidePolygon(xs, ys, k, px, py)) in++;
          }
        if (!in) continue;
        t.entries.push_back(WeightEntry{(uint16_t)(row * width + col), 0});
        hits.push_back(in);
        if (in > best) best = in;
      }
    for (size_t e = first; e < t.entries.size(); e++)
      t.entries[e].weight = (uint8_t)((hits[e - first] * 255 + best / 2) / best);
    t.panels[i] = PanelWeights{(uint16_t)first, (uint16_t)(t.entries.size() - first)};
  }
}

// Colour of panel i: the hue of the weighted mean of its cells, scaled so its strongest channel equals the brightest
// weighted cell. A uniform frame gives exactly that colour, and a single lit cell under a panel lights it fully
// instead of being divided by the number of cells. pixel(cell) returns WLED's 0xWWRRGGBB; so does the result.
template <typename PixelFn>
inline uint32_t samplePanel(const WeightTable &t, int i, PixelFn pixel) {
  const PanelWeights &pw = t.panels[i];
  uint32_t sum[4] = {0, 0, 0, 0};
  uint32_t peak = 0;  // weight × channel, up to 255²
  for (unsigned k = 0; k < pw.count; k++) {
    const WeightEntry &e = t.entries[pw.first + k];
    uint32_t c = pixel(e.cell), w = e.weight, top = 0;
    for (int ch = 0; ch < 4; ch++) {
      uint32_t v = (c >> (8 * ch)) & 0xFF;
      sum[ch] += v * w;
      if (v > top) top = v;
    }
    if (top * w > peak) peak = top * w;
  }
  uint32_t big = sum[0];
  for (int ch = 1; ch < 4; ch++)
    if (sum[ch] > big) big = sum[ch];
  if (!big) return 0;
  uint64_t div = (uint64_t)big * 255;
  uint32_t out = 0;
  for (int ch = 0; ch < 4; ch++) out |= (uint32_t)(((uint64_t)sum[ch] * peak + div / 2) / div) << (8 * ch);
  return out;
}

}  // namespace leafbus
