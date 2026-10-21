"""Script automatizado para iniciar a aplicação Dash e capturar screenshots reais
de diferentes cenários de consulta e regeneração de frota em Belo Horizonte.
"""

import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT_DIR = Path(__file__).resolve().parent.parent
IMAGES_DIR = ROOT_DIR / "docs" / "images"
APP_URL = "http://127.0.0.1:8055"


def capture_interface_screenshots() -> None:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    # Inicia o servidor Dash em processo dedicado na porta 8055
    server_cmd = [
        str(ROOT_DIR / ".venv" / "bin" / "python"),
        "-c",
        (
            "from app import create_dash_app; "
            "app = create_dash_app(); "
            "app.run(host='127.0.0.1', port=8055, debug=False)"
        ),
    ]
    proc = subprocess.Popen(
        server_cmd,
        cwd=str(ROOT_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        time.sleep(3.5)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1680, "height": 1020},
                device_scale_factor=1.5,
            )
            page = context.new_page()
            page.goto(APP_URL, wait_until="networkidle", timeout=45000)
            page.wait_for_selector(".leaflet-tile-loaded", timeout=30000)
            time.sleep(2.5)

            # Screenshot 1: Visão inicial (Jardim Atlântico / Pampulha, N=250, Raio=2.0 km)
            shot1 = IMAGES_DIR / "screenshot_consulta_inicial.png"
            page.screenshot(path=str(shot1), full_page=True)
            print(f"Saved: {shot1}")

            # Screenshot 2: Busca por restaurante na Savassi ('SAVASSI') e regeneração para N=600
            search_input = page.locator("#search-text-input")
            search_input.fill("SAVASSI")
            time.sleep(1.2)

            courier_input = page.locator("#courier-count-input")
            courier_input.fill("600")
            page.locator("#generate-couriers-btn").click()
            page.wait_for_load_state("networkidle")
            time.sleep(2.8)

            shot2 = IMAGES_DIR / "screenshot_savassi_n600.png"
            page.screenshot(path=str(shot2), full_page=True)
            print(f"Saved: {shot2}")

            # Screenshot 3: Consulta no Centro ('AFONSO PENA') com ajuste de frota N=400
            search_input.fill("AFONSO PENA")
            time.sleep(1.2)
            courier_input.fill("400")
            page.locator("#generate-couriers-btn").click()
            page.wait_for_load_state("networkidle")
            time.sleep(2.8)

            shot3 = IMAGES_DIR / "screenshot_afonso_pena_n400.png"
            page.screenshot(path=str(shot3), full_page=True)
            print(f"Saved: {shot3}")

            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    capture_interface_screenshots()

