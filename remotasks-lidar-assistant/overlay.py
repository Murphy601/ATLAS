"""Local Flask + Three.js overlay that visualizes cuboids on localhost only."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from flask import Flask, Response, jsonify

import config

logger = logging.getLogger("lidar.overlay")

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>LiDAR cuboid overlay</title>
  <style>
    html, body { margin: 0; height: 100%; background: #0b1020; color: #d7e1ff; font-family: ui-sans-serif, system-ui; }
    #hud { position: absolute; top: 12px; left: 12px; z-index: 2; background: rgba(8,12,24,.72); padding: 10px 14px; border-radius: 8px; }
    canvas { display: block; }
  </style>
</head>
<body>
  <div id="hud">Waiting for analysis…</div>
  <script type="importmap">
    { "imports": { "three": "https://unpkg.com/three@0.160.0/build/three.module.js" } }
  </script>
  <script type="module">
    import * as THREE from "three";
    const hud = document.getElementById("hud");
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(55, innerWidth / innerHeight, 0.1, 500);
    camera.position.set(12, 12, 12);
    camera.lookAt(0, 0, 0);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(innerWidth, innerHeight);
    document.body.appendChild(renderer.domElement);
    scene.add(new THREE.GridHelper(40, 40, 0x335577, 0x1b2740));
    scene.add(new THREE.AxesHelper(3));
    const group = new THREE.Group();
    scene.add(group);

    function drawCuboids(payload) {
      while (group.children.length) group.remove(group.children[0]);
      const cuboids = payload.cuboids || [];
      hud.textContent = cuboids.length
        ? `${cuboids.length} cuboid(s) from ${payload.source || "latest frame"}`
        : "No cuboids yet — load a LiDAR Lite task in the Playwright window";
      for (const box of cuboids) {
        const geom = new THREE.BoxGeometry(box.dx || 1, box.dz || 1, box.dy || 1);
        const mat = new THREE.MeshBasicMaterial({ color: 0x6ea8fe, wireframe: true });
        const mesh = new THREE.Mesh(geom, mat);
        mesh.position.set(box.x || 0, box.z || 0, box.y || 0);
        if (box.rotation && box.rotation.length === 3) {
          const m = new THREE.Matrix4();
          m.set(
            box.rotation[0][0], box.rotation[0][1], box.rotation[0][2], 0,
            box.rotation[1][0], box.rotation[1][1], box.rotation[1][2], 0,
            box.rotation[2][0], box.rotation[2][1], box.rotation[2][2], 0,
            0, 0, 0, 1
          );
          mesh.setRotationFromMatrix(m);
        } else {
          mesh.rotation.y = box.theta || 0;
        }
        group.add(mesh);
      }
    }

    async function poll() {
      try {
        const res = await fetch("/api/result");
        if (res.ok) drawCuboids(await res.json());
      } catch (err) {
        hud.textContent = "Overlay waiting for analysis_result.json";
      }
    }
    poll();
    setInterval(poll, 1000);
    function tick() {
      renderer.render(scene, camera);
      requestAnimationFrame(tick);
    }
    tick();
    addEventListener("resize", () => {
      camera.aspect = innerWidth / innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(innerWidth, innerHeight);
    });
  </script>
</body>
</html>
"""


def create_app(result_path: Path | None = None) -> Flask:
    app = Flask(__name__)
    path = Path(result_path or config.ANALYSIS_RESULT)

    @app.get("/")
    def index() -> Response:
        return Response(HTML_PAGE, mimetype="text/html")

    @app.get("/api/result")
    def result():
        if not path.exists():
            return jsonify({"object_count": 0, "cuboids": [], "source": None})
        return jsonify(json.loads(path.read_text(encoding="utf-8")))

    return app


def start_overlay_thread(host: str | None = None, port: int | None = None) -> threading.Thread:
    app = create_app()
    host = host or config.OVERLAY_HOST
    port = port or config.OVERLAY_PORT

    def _run() -> None:
        logger.info("Cuboid overlay at http://%s:%s", host, port)
        app.run(host=host, port=port, debug=False, use_reloader=False)

    thread = threading.Thread(target=_run, name="lidar-overlay", daemon=True)
    thread.start()
    return thread
