from __future__ import annotations

import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urlsplit

from .errors import BrokerError
from .storage import Store


def setup():
    store = Store()
    root = tk.Tk()
    root.title("KAIST Login — 로컬 계정 설정")
    root.geometry("580x370")
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="비밀번호는 이 창에만 입력하세요.", font=("", 16)).pack(anchor="w")
    ttk.Label(frame, text="macOS 키체인 / Windows 자격 증명 관리자에 저장합니다.").pack(anchor="w", pady=(4, 16))
    entries = {}
    config = store.config()
    for key, label in (("username", "KAIST 포털 아이디"), ("password", "비밀번호"), ("external_email", "외부 Gmail 주소 (선택)")):
        ttk.Label(frame, text=label).pack(anchor="w")
        entry = ttk.Entry(frame, show="•" if key == "password" else "", width=60)
        entry.pack(fill="x", pady=(2, 10))
        if key != "password":
            entry.insert(0, config.get(key, ""))
        entries[key] = entry

    def save():
        try:
            email = entries["external_email"].get().strip()
            store.save_account(entries["username"].get(), entries["password"].get(), email)
            entries["password"].delete(0, "end")
            messagebox.showinfo("저장 완료", "계정을 저장했습니다. Gmail 연결은 gmail-connect 명령으로 진행하세요.", parent=root)
            root.destroy()
        except Exception:
            messagebox.showerror("저장 실패", "입력값과 운영체제 보안 저장소 접근 권한을 확인하세요.", parent=root)

    ttk.Button(frame, text="보안 저장소에 저장", command=save).pack(anchor="e", pady=8)
    root.mainloop()


def select_client_file():
    root = tk.Tk()
    root.withdraw()
    path = filedialog.askopenfilename(title="Google Desktop OAuth client JSON 선택", filetypes=[("JSON", "*.json")])
    root.destroy()
    return path


def mail_options(store=None):
    store = store or Store()
    root = tk.Tk()
    root.title("KAIST Login — 인증메일 옵션")
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill="both", expand=True)
    enabled = tk.BooleanVar(value=store.config().get("delete_otp_email", False))
    ttk.Checkbutton(frame, text="로그인 성공 후 사용한 인증메일 한 통을 휴지통으로 이동", variable=enabled).pack(anchor="w")
    ttk.Label(frame, text="기본값은 꺼짐입니다. 인증에 실패한 메일은 보존합니다.").pack(anchor="w", pady=12)
    def save():
        store.set_mail_cleanup(enabled.get())
        root.destroy()
    ttk.Button(frame, text="옵션 저장", command=save).pack(anchor="e")
    root.mainloop()


def gmail_imap_setup(delete_otp_email=None):
    from .gmail_imap import check_connection
    store = Store()
    root = tk.Tk()
    root.title("KAIST Login — Gmail 앱 비밀번호 연결")
    root.geometry("650x420")
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Google Cloud 없이 Gmail 연결", font=("", 16)).pack(anchor="w")
    ttk.Label(frame, text="Google 계정의 2단계 인증을 켠 뒤 앱 비밀번호를 한 번 만드세요.\n일반 Google 비밀번호가 아닌, 별도로 발급한 16자리 앱 비밀번호를 입력하세요.", wraplength=600).pack(anchor="w", pady=12)
    ttk.Label(frame, text="외부 Gmail 주소").pack(anchor="w")
    email = ttk.Entry(frame, width=70)
    email.insert(0, store.config().get("external_email", ""))
    email.pack(fill="x", pady=(2, 12))
    ttk.Label(frame, text="Google 앱 비밀번호 (공백을 포함해 붙여넣어도 됩니다)").pack(anchor="w")
    password = ttk.Entry(frame, show="•", width=70)
    password.pack(fill="x", pady=(2, 12))
    enabled = tk.BooleanVar(value=store.config().get("delete_otp_email", False) if delete_otp_email is None else delete_otp_email)
    ttk.Checkbutton(frame, text="로그인 성공 후 사용한 인증메일을 휴지통으로 이동", variable=enabled).pack(anchor="w")
    notice = tk.StringVar(value="앱 비밀번호는 이 기기의 OS 보안 저장소에 보관합니다.")
    ttk.Label(frame, textvariable=notice, wraplength=600).pack(anchor="w", pady=14)
    pool = ThreadPoolExecutor(max_workers=1)
    alive = True
    def close():
        nonlocal alive
        alive = False
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", close)

    def save():
        address, secret = email.get().strip(), "".join(password.get().split())
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", address) or not re.fullmatch(r"[A-Za-z0-9]{16}", secret):
            notice.set("Gmail 주소와 Google이 발급한 16자리 앱 비밀번호를 확인하세요.")
            return
        button.configure(state="disabled")
        notice.set("Gmail 연결 확인 중…")
        future = pool.submit(check_connection, address, secret)
        def finished():
            if not alive:
                return
            if not future.done():
                root.after(100, finished)
                return
            try:
                future.result()
                store.save_imap(address, secret, enabled.get())
                password.delete(0, "end")
                messagebox.showinfo("연결 완료", "Gmail 앱 비밀번호를 저장했습니다. 주기적인 OAuth 재승인은 필요 없습니다.", parent=root)
                close()
            except Exception as exc:
                code = exc.code if isinstance(exc, BrokerError) else "operation_failed"
                notice.set(f"연결 실패 ({code}). 앱 비밀번호와 계정의 IMAP 사용 가능 여부를 확인하세요.")
                button.configure(state="normal")
        root.after(100, finished)
    button = ttk.Button(frame, text="연결 확인 후 보안 저장소에 저장", command=save)
    button.pack(anchor="e")
    try:
        root.mainloop()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def confirm_forget():
    root = tk.Tk()
    root.withdraw()
    answer = messagebox.askyesno("로컬 연결 삭제", "저장한 KAIST 비밀번호, Gmail 앱 비밀번호·토큰, 로그인 세션을 이 기기에서 삭제할까요?\nGoogle 계정의 앱 비밀번호·권한은 별도로 취소해야 합니다.", parent=root)
    root.destroy()
    return answer


# The wizard reads only element metadata, never current values or innerHTML.
ELEMENTS_JS = """() => {
  function selector(e) {
    if(e.id) return '#' + CSS.escape(e.id);
    const parts=[];
    while(e && e !== document.body) {
      const tag=e.tagName.toLowerCase();
      const siblings=Array.from(e.parentElement.children).filter(x=>x.tagName===e.tagName);
      parts.unshift(tag+':nth-of-type('+(siblings.indexOf(e)+1)+')');
      e=e.parentElement;
    }
    return 'body > '+parts.join(' > ');
  }
  return Array.from(document.querySelectorAll('input,button,a,[role="button"],[role="tab"]'))
    .filter(e=>e.type!=='password' && e.type!=='hidden' && e.getClientRects().length)
    .map(e=>({selector:selector(e),tag:e.tagName.toLowerCase(),type:e.type||'',
      text:(e.innerText||e.getAttribute('aria-label')||e.getAttribute('placeholder')||e.id||e.name||e.tagName).trim().slice(0,160),
      markerText:(e.innerText||'').trim()}));
}"""


async def calibrate(site):
    from .browser import session, reach_sso, submit_password, save_session
    from .policy import SITES, SSO_HOST, auth_url, host
    store = Store()
    async with session(store) as (context, page):
        await reach_sso(page, site, store)
        root = tk.Tk()
        root.title("KAIST Login — 최초 화면 등록")
        root.geometry("850x680")
        frame = ttk.Frame(root, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="브라우저에서 1차 로그인 후 인증 화면을 등록하세요.", font=("", 15)).pack(anchor="w")
        ttk.Label(frame, text="화면 조사 → 요소 선택 → 인증 규칙 저장. 이후 직접 로그인 완료 → 성공 화면 등록.\n인증번호·비밀번호·메일 본문은 이 도구의 출력으로 보내지 않습니다.").pack(anchor="w", pady=8)
        notice = tk.StringVar(value="준비")
        rows, mapping, pending = {}, {}, set()
        done = False

        def close():
            nonlocal done
            done = True
        root.protocol("WM_DELETE_WINDOW", close)

        async def guarded(coro):
            try:
                await coro
            except Exception as exc:
                notice.set(exc.code if isinstance(exc, BrokerError) else "작업 실패. 브라우저와 설정을 확인하세요.")

        def launch(coro):
            task = asyncio.create_task(guarded(coro))
            pending.add(task)
            task.add_done_callback(pending.discard)

        async def password():
            await submit_password(page, store, [])
            notice.set("1차 로그인 제출 완료. 인증 화면에서 화면 조사를 누르세요.")

        scanned_path = ""
        async def scan():
            nonlocal scanned_path
            if host(page.url) not in {SSO_HOST, host(SITES[site])}:
                raise BrokerError("unexpected_origin")
            scanned_path = urlsplit(page.url).path
            elements = await page.evaluate(ELEMENTS_JS)
            mapping.clear()
            for i, item in enumerate(elements):
                mapping[f'{i + 1}. {item["text"]} [{item["tag"]}]'] = item
            for key, row in rows.items():
                choices = [""] + [label for label, item in mapping.items()
                                  if (key != "code" or (item["tag"] == "input" and item["type"] in {"text", "tel", "number"}))]
                row["values"] = choices
                row.set("")
            notice.set("현재 화면 요소를 불러왔습니다. 변경된 화면은 다시 조사하세요.")

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=8)
        ttk.Button(buttons, text="저장된 계정으로 1차 로그인", command=lambda: launch(password())).pack(side="left")
        ttk.Button(buttons, text="현재 화면 조사", command=lambda: launch(scan())).pack(side="left", padx=8)
        for key, label in (("choose_email", "외부 이메일 방식 선택 (필요할 때만)"), ("send", "인증번호 발송 (자동 발송이면 비움)"), ("code", "인증번호 입력란"), ("verify", "인증 확인 버튼"), ("success", "로그인 후에만 보이는 메뉴/링크 (성공 화면 등록용)")):
            ttk.Label(frame, text=label).pack(anchor="w", pady=(7, 0))
            row = ttk.Combobox(frame, state="readonly", width=90)
            row.pack(fill="x")
            rows[key] = row
        fields = {}
        for key, label in (("sender", "인증메일의 실제 발신 이메일 주소"), ("subject_phrase", "인증메일 제목에 포함되는 고정 문구")):
            ttk.Label(frame, text=label).pack(anchor="w", pady=(7, 0))
            field = ttk.Entry(frame)
            field.pack(fill="x")
            field.insert(0, store.config().get("mfa", {}).get(key, ""))
            fields[key] = field

        async def save_rule():
            if host(page.url) != SSO_HOST or urlsplit(page.url).path != scanned_path:
                raise BrokerError("scan_mfa_page_first")
            rule = {"path": scanned_path}
            for key in ("choose_email", "send", "code", "verify"):
                rule[key] = mapping[rows[key].get()]["selector"] if rows[key].get() else ""
            rule.update({key: entry.get().strip() for key, entry in fields.items()})
            if (not rule["code"] or not rule["verify"] or not rule["subject_phrase"]
                    or not re.fullmatch(r"[A-Za-z0-9._+%-]+@[A-Za-z0-9.-]+", rule["sender"])):
                raise BrokerError("mfa_fields_required")
            config = store.config()
            config["mfa"] = rule
            store.save_config(config)
            notice.set("인증 화면 규칙 저장 완료. 브라우저에서 로그인 후 성공 화면도 등록하세요.")

        async def success():
            if host(page.url) != host(SITES[site]) or auth_url(page.url):
                raise BrokerError("service_page_required")
            item = mapping.get(rows["success"].get())
            if not item or not item["markerText"]:
                raise BrokerError("select_success_marker")
            locator = page.locator(item["selector"])
            if await locator.count() != 1 or not await locator.is_visible() or (await locator.inner_text()).strip() != item["markerText"]:
                raise BrokerError("scan_service_page_first")
            config = store.config()
            config.setdefault("success", {})[site] = {"selector": item["selector"], "text": item["markerText"]}
            config["login_blocked"] = False
            store.save_config(config)
            await save_session(context, store)
            notice.set("로그인 성공 화면과 암호화 세션 저장 완료. 창을 닫아도 됩니다.")

        buttons2 = ttk.Frame(frame)
        buttons2.pack(fill="x", pady=16)
        ttk.Button(buttons2, text="인증 화면 규칙 저장", command=lambda: launch(save_rule())).pack(side="left")
        ttk.Button(buttons2, text="로그인 성공 화면 등록", command=lambda: launch(success())).pack(side="left", padx=8)
        ttk.Label(frame, textvariable=notice, wraplength=780).pack(anchor="w")
        try:
            while not done:
                root.update()
                await asyncio.sleep(0.05)
        finally:
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            root.destroy()
