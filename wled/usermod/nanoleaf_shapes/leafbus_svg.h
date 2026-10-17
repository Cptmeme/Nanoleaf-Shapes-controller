#pragma once
#include <stdarg.h>
#include <stdio.h>
#include <string>
#include "leafbus_weights.h"

namespace leafbus {

namespace detail {

inline void appendf(std::string &s, const char *fmt, ...) {
  char buf[128];
  va_list ap;
  va_start(ap, fmt);
  int n = vsnprintf(buf, sizeof(buf), fmt, ap);
  va_end(ap);
  if (n > 0) s.append(buf, n < (int)sizeof(buf) ? n : (int)sizeof(buf) - 1);
}

// Where panel i meets the panel it hangs on; for panel 0, its root connector, the side facing the controller.
inline void linkPoint(const Panel *p, int i, float rotationDeg, float &x, float &y) {
  const Panel &host = p[i].parent < 0 ? p[i] : p[p[i].parent];
  int e = p[i].parent < 0 ? p[i].root : p[i].parentConn;
  float vx, vy, rx, ry;
  connectorVector(host.shape, e, vx, vy);
  rotate(vx, vy, host.o, rx, ry);
  rotate(host.x + rx, host.y + ry, rotationDeg, x, y);
}

}  // namespace detail

// Panels as placed by placePanels(). SVG has y down, so every y is negated.
inline std::string layoutSvg(const Panel *p, int n, float rotationDeg) {
  constexpr float MARGIN = 20.0f;
  std::string s;
  if (n <= 0) return s;
  float minX = 1e9f, maxX = -1e9f, minY = 1e9f, maxY = -1e9f;
  for (int i = 0; i < n; i++) {
    float xs[6], ys[6];
    int k = detail::outline(p[i], rotationDeg, xs, ys);
    for (int j = 0; j < k; j++) {
      minX = fminf(minX, xs[j]); maxX = fmaxf(maxX, xs[j]);
      minY = fminf(minY, ys[j]); maxY = fmaxf(maxY, ys[j]);
    }
  }
  s.reserve(256 + 160 * n);
  detail::appendf(s, "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"%.1f %.1f %.1f %.1f\">\n",
                  minX - MARGIN, -maxY - MARGIN, maxX - minX + 2 * MARGIN, maxY - minY + 2 * MARGIN);
  s += "<g stroke=\"#333\" stroke-width=\"1\" fill=\"#f6c343\">\n";
  for (int i = 0; i < n; i++) {
    float xs[6], ys[6];
    int k = detail::outline(p[i], rotationDeg, xs, ys);
    s += "<polygon points=\"";
    for (int j = 0; j < k; j++) detail::appendf(s, j ? " %.1f,%.1f" : "%.1f,%.1f", xs[j], -ys[j]);
    s += "\"/>\n";
  }
  s += "</g>\n<g stroke=\"none\">\n";
  for (int i = 0; i < n; i++) {
    float x, y;
    detail::linkPoint(p, i, rotationDeg, x, y);
    detail::appendf(s, "<circle cx=\"%.1f\" cy=\"%.1f\" r=\"%d\" fill=\"%s\"/>\n", x, -y,
                    p[i].parent < 0 ? 4 : 2, p[i].parent < 0 ? "#2a2" : "#c00");
  }
  s += "</g>\n<g font-size=\"12\" font-family=\"sans-serif\" text-anchor=\"middle\" dominant-baseline=\"middle\">\n";
  for (int i = 0; i < n; i++) {
    float x, y;
    detail::rotate(p[i].x, p[i].y, rotationDeg, x, y);
    detail::appendf(s, "<text x=\"%.1f\" y=\"%.1f\">%d</text>\n", x, -y, i);
  }
  s += "</g>\n</svg>\n";
  return s;
}

}  // namespace leafbus
