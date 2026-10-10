import argparse
import asyncio
import getpass
import json
import logging
import sys

from .errors import BrokerError


def parser():
    root = argparse.ArgumentParser(description="KAIST 로컬 로그인 도구 — 비밀번호 인자 없음")
    commands = root.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("setup", help="로컬 비밀번호 입력창 열기")
    setup.add_argument("--terminal", action="store_true", help="사용자 터미널에서만 getpass 사용")
    commands.add_parser("status", help="아이디와 연결 상태만 출력")
    gmail = commands.add_parser("gmail-connect", help="Gmail 앱 비밀번호를 로컬 입력창에서 등록")
    gmail.add_argument("--method", choices=["imap", "oauth"], default="imap")
    gmail.add_argument("--delete-otp-email", action=argparse.BooleanOptionalAction, default=None)
    options = commands.add_parser("mail-options", help="인증메일 자동 삭제 설정 (기본 꺼짐)")
    options.add_argument("--delete-otp-email", action=argparse.BooleanOptionalAction, default=None)
    for name in ("login", "calibrate"):
        command = commands.add_parser(name)
        command.add_argument("site", choices=["klms", "dooray"])
        if name == "login":
            command.add_argument("--manual", action="store_true", help="브라우저에서 직접 로그인")
    read = commands.add_parser("read")
    read.add_argument("site", choices=["klms", "dooray"])
    read.add_argument("--url")
    read.add_argument("--max-chars", type=int, default=20000)
    commands.add_parser("reset-login", help="실패 후 로컬 확인을 거쳐 재시도 허용")
    commands.add_parser("forget", help="확인창을 거쳐 로컬 비밀정보 삭제")
    commands.add_parser("serve", help="MCP stdio 서버")
    config = commands.add_parser("mcp-config", help="현재 Python 경로로 MCP 설정 출력")
    config.add_argument("--client", choices=["codex", "claude-desktop", "claude-code"], default="codex")
    return root


def perform(args):
    if args.command == "serve":
        from .server import run
        run()
        return None
    if args.command == "mcp-config":
        if args.client != "codex":
            server = {"command": sys.executable, "args": ["-m", "kaist_login", "serve"]}
            if args.client == "claude-code":
                server["type"] = "stdio"
            print(json.dumps({"mcpServers": {"kaist_login": server}}, ensure_ascii=False, indent=2))
            return None
        # JSON string escaping is compatible with a TOML basic string here.
        print('[mcp_servers.kaist_login]\ncommand = ' + json.dumps(sys.executable)
              + '\nargs = ["-m", "kaist_login", "serve"]\ntool_timeout_sec = 240')
        return None
    from .storage import Store
    if args.command == "setup":
        if args.terminal:
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                raise BrokerError("interactive_terminal_required")
            username = input("KAIST 포털 아이디: ")
            password = getpass.getpass("KAIST 비밀번호 (표시되지 않음): ")
            email = input("외부 Gmail 주소 (선택): ")
            Store().save_account(username, password, email)
        else:
            from .ui import setup
            setup()
        return {"status": "setup_closed"}
    if args.command == "status":
        return Store().status()
    if args.command == "gmail-connect":
        if args.method == "imap":
            from .ui import gmail_imap_setup
            gmail_imap_setup(delete_otp_email=args.delete_otp_email)
            return {"status": "gmail_setup_closed"}
        from .gmail import connect
        from .ui import select_client_file
        path = select_client_file()
        if not path:
            return {"status": "cancelled"}
        connect(Store(), path, args.delete_otp_email)
        return {"status": "gmail_connected"}
    if args.command == "mail-options":
        store = Store()
        if args.delete_otp_email is None:
            from .ui import mail_options
            mail_options(store)
        else:
            store.set_mail_cleanup(args.delete_otp_email)
        return {"status": "ok", "delete_otp_email": store.config().get("delete_otp_email", False)}
    if args.command == "calibrate":
        from .ui import calibrate
        asyncio.run(calibrate(args.site))
        return {"status": "calibration_closed"}
    if args.command in {"login", "read"}:
        from .browser import Broker
        broker = Broker()
        if args.command == "login":
            return asyncio.run(broker.login(args.site, manual=args.manual))
        return asyncio.run(broker.read(args.site, args.url, args.max_chars))
    if args.command == "reset-login":
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        approved = messagebox.askyesno("로그인 재시도", "아이디/비밀번호와 계정 상태를 확인했나요? 자동 로그인 시도를 다시 허용합니다.", parent=root)
        root.destroy()
        if approved:
            store = Store()
            config = store.config()
            config["login_blocked"] = False
            store.save_config(config)
        return {"status": "reset" if approved else "cancelled"}
    if args.command == "forget":
        from .ui import confirm_forget
        if confirm_forget():
            Store().forget_all()
            return {"status": "local_credentials_removed"}
        return {"status": "cancelled"}


def main():
    logging.disable(logging.CRITICAL)
    args = parser().parse_args()
    try:
        result = perform(args)
        if result is not None:
            print(json.dumps(result, ensure_ascii=False))
        return 0
    except BrokerError as exc:
        print(json.dumps({"status": "error", "code": exc.code}))
    except KeyboardInterrupt:
        print('{"status":"cancelled"}')
        return 130
    except Exception:
        print('{"status":"error","code":"operation_failed"}')
    return 1
