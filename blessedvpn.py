import subprocess
import sys
import shutil
import tempfile
import os
import base64
import time
import re
import concurrent.futures


def ensure_package(package, pip_name=None):
    try:
        __import__(package)
    except ImportError:
        print(f"[*] Устанавливаю {pip_name or package}...")
        subprocess.check_call([
            sys.executable, '-m', 'pip', 'install',
            '--break-system-packages', '--quiet',
            pip_name or package
        ])


ensure_package('requests')
ensure_package('pyfiglet')

import requests
import pyfiglet


# ---------- Цвета (служебные, не тема) ----------

GREEN = (80, 220, 120)
YELLOW = (230, 200, 60)
RED = (230, 70, 70)
GRAY = (130, 130, 130)


def lerp_color(start, end, t):
    return tuple(int(start[i] + (end[i] - start[i]) * t) for i in range(3))


def colorize(text, rgb):
    r, g, b = rgb
    return f'\033[38;2;{r};{g};{b}m{text}\033[0m'


def print_gradient_block(lines, start_rgb, end_rgb):
    total = len(lines) or 1
    for i, line in enumerate(lines):
        t = i / max(total - 1, 1)
        color = lerp_color(start_rgb, end_rgb, t)
        print(colorize(line, color))


def ping_color(ms):
    if ms < 100:
        return GREEN
    elif ms < 250:
        return YELLOW
    return RED


def speed_color(mbps):
    if mbps > 10:
        return GREEN
    elif mbps > 1:
        return YELLOW
    return RED


# ---------- Цветовые темы ----------

THEMES = {
    '1': {
        'name': "Сине-тёмно-синий (по умолчанию)",
        'title_start': (100, 170, 255), 'title_end': (40, 80, 200),
        'box_start': (40, 80, 200), 'box_end': (10, 15, 60),
    },
    '2': {
        'name': "Кровавo-красный",
        'title_start': (255, 110, 110), 'title_end': (180, 20, 20),
        'box_start': (180, 20, 20), 'box_end': (40, 0, 0),
    },
    '3': {
        'name': "Фиолетово-ночной",
        'title_start': (190, 140, 255), 'title_end': (100, 50, 190),
        'box_start': (100, 50, 190), 'box_end': (20, 10, 45),
    },
    '4': {
        'name': "Зелёно-хакерский",
        'title_start': (140, 255, 140), 'title_end': (30, 190, 70),
        'box_start': (30, 190, 70), 'box_end': (5, 35, 10),
    },
}

CURRENT_THEME = dict(THEMES['1'])


# ---------- Универсальная двойная рамка ----------

def print_double_box(header_text, lines, start_rgb, end_rgb):
    content_width = max(len(header_text), max(len(l) for l in lines))

    def h_line(left, mid, right):
        return left + mid * (content_width + 2) + right

    box_lines = []
    box_lines.append(h_line('╔', '═', '╗'))
    box_lines.append('║ ' + header_text.center(content_width) + ' ║')
    box_lines.append(h_line('╠', '═', '╣'))
    for line in lines:
        box_lines.append('║ ' + line.ljust(content_width) + ' ║')
    box_lines.append(h_line('╚', '═', '╝'))

    print_gradient_block(box_lines, start_rgb, end_rgb)


# ---------- Заголовок и главное меню ----------

def print_title():
    art = pyfiglet.figlet_format("BLESSED VPN", font="bloody")
    lines = [l for l in art.split('\n') if l.strip()]
    print_gradient_block(lines, CURRENT_THEME['title_start'], CURRENT_THEME['title_end'])
    print()


def print_menu_box():
    print_double_box(
        "MADE BY BLESSED",
        [
            "1. Выбрать сервер",
            "2. Автоматический выбор",
            "3. Отключить VPN",
            "4. Сменить цвет",
            "5. Выход",
        ],
        CURRENT_THEME['box_start'], CURRENT_THEME['box_end']
    )


def print_banner():
    print_title()
    print_menu_box()


def print_theme_menu():
    lines = [f"{key}. {t['name']}" for key, t in THEMES.items()]
    print_double_box("СМЕНА ЦВЕТОВОЙ ТЕМЫ", lines, CURRENT_THEME['box_start'], CURRENT_THEME['box_end'])


def change_theme():
    global CURRENT_THEME
    print_theme_menu()
    choice = input("\nВыбери тему: ").strip()
    if choice in THEMES:
        CURRENT_THEME = dict(THEMES[choice])
        print(colorize(f"[✓] Тема изменена: {THEMES[choice]['name']}", GREEN))
    else:
        print(colorize("[!] Неверный выбор", RED))


# ---------- Локализация меню установки OpenVPN ----------

TEXTS = {
    'ru': {
        'header': "ВЫБОР ПАКЕТНОГО МЕНЕДЖЕРА",
        'not_found': "[!] OpenVPN не найден в системе.",
        'choose_manager': "> Выбери свой пакетный менеджер: ",
        'invalid': "[!] Неверный выбор, установка отменена",
        'installing': "[*] Устанавливаю OpenVPN через {name} ({distro})...",
        'installed': "[✓] OpenVPN установлен",
        'failed': "[!] Установка не удалась. Возможно, нужны другие права или флаги.",
        'not_found_cmd': "[!] Команда '{cmd}' не найдена в системе.",
        'already_installed': "[*] OpenVPN уже установлен",
        'found_marker': "найден",
    },
    'en': {
        'header': "SELECT PACKAGE MANAGER",
        'not_found': "[!] OpenVPN not found on this system.",
        'choose_manager': "> Pick your package manager: ",
        'invalid': "[!] Invalid choice, installation cancelled",
        'installing': "[*] Installing OpenVPN via {name} ({distro})...",
        'installed': "[✓] OpenVPN installed",
        'failed': "[!] Installation failed. You may need different permissions or flags.",
        'not_found_cmd': "[!] Command '{cmd}' not found on this system.",
        'already_installed': "[*] OpenVPN is already installed",
        'found_marker': "found",
    },
}


# ---------- Выбор пакетного менеджера ----------

PACKAGE_MANAGERS = {
    '1':  ("pacman",       "Arch / Manjaro / EndeavourOS", ['sudo', 'pacman', '-Sy', '--noconfirm', 'openvpn']),
    '2':  ("apt",          "Debian / Ubuntu / Mint",       ['sudo', 'apt', 'install', '-y', 'openvpn']),
    '3':  ("dnf",          "Fedora / RHEL 8+",             ['sudo', 'dnf', 'install', '-y', 'openvpn']),
    '4':  ("yum",          "CentOS / RHEL 7",              ['sudo', 'yum', 'install', '-y', 'openvpn']),
    '5':  ("zypper",       "openSUSE",                     ['sudo', 'zypper', '--non-interactive', 'install', 'openvpn']),
    '6':  ("apk",          "Alpine Linux",                 ['sudo', 'apk', 'add', 'openvpn']),
    '7':  ("emerge",       "Gentoo",                       ['sudo', 'emerge', 'net-vpn/openvpn']),
    '8':  ("xbps-install", "Void Linux",                   ['sudo', 'xbps-install', '-Sy', 'openvpn']),
    '9':  ("eopkg",        "Solus",                        ['sudo', 'eopkg', 'install', '-y', 'openvpn']),
    '10': ("nix-env",      "NixOS",                        ['nix-env', '-iA', 'nixpkgs.openvpn']),
    '11': ("brew",         "macOS (Homebrew)",             ['brew', 'install', 'openvpn']),
    '12': ("pkg",          "FreeBSD",                      ['sudo', 'pkg', 'install', '-y', 'openvpn']),
    '13': ("pkg",          "Termux (Android)",             ['pkg', 'install', '-y', 'openvpn']),
    '14': ("apt",         "Termux2",                       ['apt', 'install', '-y', 'openvpn']),
}


def detect_available_managers():
    found = []
    for key, (name, _, _) in PACKAGE_MANAGERS.items():
        if shutil.which(name) is not None:
            found.append(key)
    return found


def print_pkgmgr_menu(lang='ru'):
    header_text = TEXTS[lang]['header']
    marker_text = TEXTS[lang]['found_marker']
    detected = detect_available_managers()
    lines = []
    for key, (name, distro, _) in PACKAGE_MANAGERS.items():
        marker = f"  ✓ {marker_text}" if key in detected else ""
        lines.append(f"{key:>2}. {name:<14} {distro}{marker}")

    print_double_box(header_text, lines, CURRENT_THEME['box_start'], CURRENT_THEME['box_end'])


def ensure_openvpn():
    if shutil.which('openvpn') is not None:
        print("[*] OpenVPN уже установлен / already installed")
        return

    print("\n1. Русский")
    print("2. English")
    lang_choice = input("> ").strip()
    lang = 'en' if lang_choice == '2' else 'ru'
    t = TEXTS[lang]

    print(colorize(f"\n{t['not_found']}\n", YELLOW))
    print_pkgmgr_menu(lang)

    choice = input(f"\n{t['choose_manager']}").strip()

    if choice not in PACKAGE_MANAGERS:
        print(colorize(t['invalid'], RED))
        return

    name, distro, cmd = PACKAGE_MANAGERS[choice]
    print(f"\n{t['installing'].format(name=name, distro=distro)}")

    try:
        subprocess.run(cmd, check=True)
        print(colorize(t['installed'], GREEN))
    except subprocess.CalledProcessError:
        print(colorize(t['failed'], RED))
    except FileNotFoundError:
        cmd_name = cmd[0] if cmd[0] != 'sudo' else cmd[1]
        print(colorize(t['not_found_cmd'].format(cmd=cmd_name), RED))


# ---------- Реальный пинг ----------

def real_ping(ip, count=2, timeout=1):
    try:
        result = subprocess.run(
            ['ping', '-c', str(count), '-W', str(timeout), ip],
            capture_output=True, text=True,
            timeout=count * timeout + 3
        )
        match = re.search(r'rtt min/avg/max/mdev = [\d.]+/([\d.]+)/', result.stdout)
        if match:
            return float(match.group(1))
        return None
    except (subprocess.TimeoutExpired, Exception):
        return None


def measure_real_pings(servers):
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        futures = {executor.submit(real_ping, s['ip']): s['ip'] for s in servers}
        for future in concurrent.futures.as_completed(futures):
            ip = futures[future]
            results[ip] = future.result()
    return results


# ---------- VPN Gate логика ----------

VPNGATE_API = "http://www.vpngate.net/api/iphone/"
_last_config_path = None


def get_servers():
    response = requests.get(VPNGATE_API, timeout=10)
    lines = response.text.strip().split('\n')
    lines = [l for l in lines if l and not l.startswith('*') and not l.startswith('#')]

    servers = []
    for line in lines:
        fields = line.split(',')
        if len(fields) < 15:
            continue
        try:
            server = {
                'hostname': fields[0],
                'ip': fields[1],
                'score': int(fields[2]),
                'ping': int(fields[3]),
                'speed': int(fields[4]),
                'country': fields[5],
                'country_code': fields[6],
                'config_b64': fields[14],
            }
            if server['config_b64']:
                servers.append(server)
        except (ValueError, IndexError):
            continue

    return servers


def show_server_list(servers):
    sorted_servers = sorted(servers, key=lambda s: s['speed'], reverse=True)[:20]

    print("\n[*] Замеряю реальный пинг до серверов...")
    real_pings = measure_real_pings(sorted_servers)

    print("\n   №  | Страна          | Заявл.  | Реальный | Скорость")
    print("  " + "-" * 65)
    for i, s in enumerate(sorted_servers, 1):
        speed_mbps = s['speed'] / 1_000_000
        claimed_str = colorize(f"{s['ping']:>4}ms", ping_color(s['ping']))

        real = real_pings.get(s['ip'])
        if real is None:
            real_str = colorize("  ——  ", GRAY)
        else:
            real_str = colorize(f"{real:>5.0f}ms", ping_color(real))

        speed_str = colorize(f"{speed_mbps:>6.1f} Mbps", speed_color(speed_mbps))
        print(f"  {i:>2}  | {s['country'][:15]:<15} | {claimed_str} | {real_str}   | {speed_str}")

    return sorted_servers


def pick_best_server(servers):
    return max(servers, key=lambda s: s['score'])


def get_current_ip():
    try:
        return requests.get('https://ifconfig.me', timeout=5).text.strip()
    except requests.exceptions.RequestException:
        return None


def connect_vpn(server):
    global _last_config_path

    print(f"\n[*] Подключение к {server['country']} ({server['ip']})...")

    old_ip = get_current_ip()

    config_data = base64.b64decode(server['config_b64']).decode('utf-8', errors='ignore')

    if _last_config_path and os.path.exists(_last_config_path):
        os.unlink(_last_config_path)

    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.ovpn', delete=False)
    tmp.write(config_data)
    tmp.close()
    _last_config_path = tmp.name

    try:
        subprocess.Popen(
            ['sudo', 'openvpn', '--config', tmp.name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        print("[!] OpenVPN не установлен.")
        return

    print("[*] Устанавливаю соединение, подожди немного...")
    time.sleep(8)

    new_ip = get_current_ip()

    if new_ip and old_ip and new_ip != old_ip:
        print(colorize(f"[✓] Подключено! Новый IP: {new_ip}", GREEN))
    elif new_ip and old_ip and new_ip == old_ip:
        print(colorize("[!] IP не изменился — туннель, возможно, не поднялся", RED))
    else:
        print(colorize("[!] Не удалось проверить IP", YELLOW))

    print("[*] Возврат в меню...\n")


def disconnect_vpn():
    global _last_config_path

    print("\n[*] Отключаю VPN...")
    result = subprocess.run(['sudo', 'pkill', 'openvpn'])

    if _last_config_path and os.path.exists(_last_config_path):
        os.unlink(_last_config_path)
        _last_config_path = None

    if result.returncode == 0:
        print(colorize("[✓] VPN отключен", GREEN))
    else:
        print(colorize("[!] Активного подключения не найдено", YELLOW))

    print()


def select_and_connect():
    print("[*] Загружаю список серверов...")
    try:
        servers = get_servers()
    except requests.exceptions.RequestException as e:
        print(f"[!] Ошибка получения списка серверов: {e}")
        return
    if not servers:
        print("[!] Не удалось получить список серверов")
        return

    sorted_servers = show_server_list(servers)
    try:
        idx = int(input("\nВыбери номер сервера: ")) - 1
        if idx < 0 or idx >= len(sorted_servers):
            print("[!] Неверный номер")
            return
    except ValueError:
        print("[!] Введи число")
        return

    connect_vpn(sorted_servers[idx])


def auto_connect():
    print("[*] Загружаю список серверов...")
    try:
        servers = get_servers()
    except requests.exceptions.RequestException as e:
        print(f"[!] Ошибка получения списка серверов: {e}")
        return
    if not servers:
        print("[!] Не удалось получить список серверов")
        return

    best = pick_best_server(servers)
    connect_vpn(best)


def main():
    ensure_openvpn()

    while True:
        print_banner()
        choice = input("\n> ").strip()

        if choice == '1':
            select_and_connect()
        elif choice == '2':
            auto_connect()
        elif choice == '3':
            disconnect_vpn()
        elif choice == '4':
            change_theme()
        elif choice == '5':
            print("Выход.")
            break
        else:
            print("[!] Неверный выбор\n")
            continue

        input("Нажми Enter чтобы вернуться в меню...")
        os.system('clear')


if __name__ == '__main__':
    main()
