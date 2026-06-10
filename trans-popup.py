#!/usr/bin/python3
"""trans-popup — select text in terminal → Chinese translation popup"""

import subprocess, threading, time, re, signal, json, os
from urllib.request import urlopen
from urllib.parse import quote
from Xlib import display as _xlib_display
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib

CSS = b"""
#card {
    background-color: #e53935;
    border-radius: 0;
}
#trans { color: #ffffff; font-size: 17px; }
"""

_xdpy  = _xlib_display.Display()
_xroot = _xdpy.screen().root

def mouse_held():
    try:
        return bool(_xroot.query_pointer().mask & 0x100)  # Button1Mask
    except:
        return False

def get_selection():
    # try PRIMARY first (mouse drag), fall back to CLIPBOARD
    for sel in ('primary', 'clipboard'):
        try:
            r = subprocess.run(['xclip', '-selection', sel, '-o'],
                               capture_output=True, text=True, timeout=1)
            text = r.stdout.strip()
            if text:
                # strip surrounding punctuation that got swept into selection
                text = re.sub(r'^[^\w]+|[^\w一-鿿]+$', '', text)
                return text
        except:
            pass
    return ""

def contains_chinese(text):
    # Count Chinese characters
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    # Count English letters
    english_chars = sum(1 for c in text if c.isascii() and c.isalpha())
    # Only classify as Chinese if Chinese characters exceed 30% of English letters,
    # filtering out stray Tesseract OCR noise characters in English selections.
    if chinese_chars > 0 and (english_chars == 0 or chinese_chars / english_chars > 0.3):
        return True
    return False

def should_translate(text):
    if not text or len(text) > 1000:
        return False
    # Must contain at least one letter (supports English, Chinese, Japanese, etc. but filters out pure numbers/punctuation)
    return any(c.isalpha() for c in text)

# --- Persistent Local Cache System ---
CACHE_DIR = os.path.expanduser("~/.cache/trans-popup")
CACHE_FILE = os.path.join(CACHE_DIR, "cache.json")
_cache_lock = threading.Lock()

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {}

_cache = load_cache()

def save_cache():
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with _cache_lock:
            temp_cache = _cache.copy()
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(temp_cache, f, ensure_ascii=False, indent=2)
    except:
        pass

def translate(text):
    key = text.lower().strip()
    with _cache_lock:
        if key in _cache:
            return _cache[key]
    
    result = _translate_api(text)
    
    with _cache_lock:
        _cache[key] = result
        if len(_cache) > 2000:
            # Drop oldest 200 entries to save disk space
            for k in list(_cache)[:200]:
                del _cache[k]
    # Asynchronously save to avoid blocking execution
    threading.Thread(target=save_cache, daemon=True).start()
    return result

def _translate_api(text):
    tl = "en" if contains_chinese(text) else "zh-CN"
    # Auto-fallback mirror domains for reliability and speed inside China
    urls = [
        f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={tl}&dt=t&q={quote(text)}",
        f"https://translate.google.com/translate_a/single?client=gtx&sl=auto&tl={tl}&dt=t&q={quote(text)}"
    ]
    for url in urls:
        try:
            with urlopen(url, timeout=3.0) as r:
                data = json.loads(r.read())
            zh = "".join(seg[0] for seg in data[0] if seg[0])
            if zh:
                return zh, ""
        except Exception:
            continue
    return "—", ""

def speak(text):
    try:
        from gtts import gTTS
        import tempfile, os
        lang = 'zh-CN' if contains_chinese(text) else 'en'
        tts = gTTS(text=text, lang=lang, slow=True)
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
            tmp = f.name
        tts.save(tmp)
        subprocess.run(['ffplay', '-nodisp', '-autoexit', '-loglevel', 'quiet', tmp])
        os.unlink(tmp)
    except Exception:
        lang_say = 'zh' if contains_chinese(text) else 'en'
        subprocess.Popen(['spd-say', '-l', lang_say, text],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def mouse_pos():
    try:
        ptr = Gdk.Display.get_default().get_default_seat().get_pointer()
        _, x, y = ptr.get_position()
        return x, y
    except:
        return 300, 300

def log_ocr(text, zh):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        log_file = os.path.join(CACHE_DIR, "ocr.log")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}]\n")
            f.write(f"Original: {text}\n")
            f.write(f"Translated: {zh}\n")
            f.write("-" * 40 + "\n")
    except:
        pass


class Popup(Gtk.Window):
    def __init__(self, orig, zh, pron, x, y):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.orig = orig  # Save the original text to allow dynamic updates
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        # override-redirect bypasses compositor completely — no shadow
        self.connect("realize", lambda w: w.get_window().set_override_redirect(True))

        screen = self.get_screen()
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        card = Gtk.EventBox()
        card.set_name("card")
        card.connect("button-press-event", lambda *_: self.destroy())

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.set_margin_top(8); row.set_margin_bottom(8)
        row.set_margin_start(14); row.set_margin_end(10)
        row.set_valign(Gtk.Align.CENTER)

        self.trans_lbl = Gtk.Label(label=zh)
        self.trans_lbl.set_name("trans")
        self.trans_lbl.set_halign(Gtk.Align.START)
        self.trans_lbl.set_line_wrap(True)
        self.trans_lbl.set_max_width_chars(36)
        row.pack_start(self.trans_lbl, True, True, 0)
        row.pack_end(self.make_speaker_icon(), False, False, 0)

        card.add(row)
        self.add(card)

        sw = screen.get_width()
        sh = screen.get_height()
        self.move(min(x + 16, sw - 320), min(y + 36, sh - 100))

        GLib.timeout_add(5000, lambda: self.destroy() or False)
        self.show_all()

    def make_speaker_icon(self):
        da = Gtk.DrawingArea()
        da.set_size_request(22, 22)

        def draw(widget, cr):
            cr.set_source_rgb(1, 1, 1)
            cr.set_line_width(1.8)
            cr.set_line_cap(1)   # ROUND
            cr.set_line_join(1)  # ROUND
            cr.rectangle(3, 8, 5, 8)
            cr.stroke()
            cr.move_to(8, 8)
            cr.line_to(14, 4)
            cr.line_to(14, 20)
            cr.line_to(8, 16)
            cr.stroke()
            for r in (3.5, 6.0):
                cr.arc(16, 12, r, -0.65, 0.65)
                cr.stroke()
            return False

        da.connect("draw", draw)
        eb = Gtk.EventBox()
        eb.set_valign(Gtk.Align.CENTER)
        eb.set_vexpand(False)
        eb.add(da)
        eb.connect("button-press-event",
                   lambda *_: threading.Thread(target=speak, args=(self.orig,), daemon=True).start() or True)
        return eb

    def update_text(self, new_zh, new_orig=None):
        self.trans_lbl.set_text(new_zh)
        if new_orig is not None:
            self.orig = new_orig


class Daemon:
    def __init__(self):
        self.last = ""
        self.popup = None

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()
        Gtk.main()

    def _loop(self):
        while True:
            time.sleep(0.12)

            if mouse_held():
                continue

            text = get_selection()
            if not text or text == self.last or not should_translate(text):
                continue

            self.last = text
            x, y = mouse_pos()

            # 1. Instantly display loading pop-up in main thread
            GLib.idle_add(self._show_loading, text, x, y)

            # 2. Debounce and retrieve translation in background thread
            def trigger_translation(t):
                time.sleep(0.15)
                if mouse_held():
                    GLib.idle_add(self._safe_destroy)
                    return

                zh_res, _ = translate(t)
                GLib.idle_add(self._safe_update, zh_res)

            threading.Thread(target=trigger_translation, args=(text,), daemon=True).start()

    def _show_loading(self, orig, x, y):
        if self.popup:
            try: self.popup.destroy()
            except: pass
        self.popup = Popup(orig, "...", "", x, y)

    def _safe_update(self, zh):
        if self.popup:
            try:
                self.popup.update_text(zh)
            except Exception:
                pass

    def _safe_destroy(self):
        if self.popup:
            try:
                self.popup.destroy()
                self.popup = None
            except Exception:
                pass


def clean_ocr_text(text):
    if not text:
        return ""
    
    # 1. Split into lines, strip padding, ignore empty lines
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    if not lines:
        return ""
        
    cleaned_text = ""
    for i, line in enumerate(lines):
        if i == 0:
            cleaned_text = line
            continue
            
        # Clean trailing hyphens in English wrap-arounds
        if cleaned_text.endswith('-'):
            cleaned_text = cleaned_text[:-1] + line
        else:
            last_char = cleaned_text[-1] if cleaned_text else ""
            first_char = line[0] if line else ""
            
            # Detect ASCII letters/numbers on both sides
            is_last_eng = last_char.isascii() and (last_char.isalnum() or last_char in ".,!?")
            is_first_eng = first_char.isascii() and first_char.isalnum()
            
            # Connect English lines with space, tight-connect Chinese lines directly
            if is_last_eng and is_first_eng:
                cleaned_text += " " + line
            else:
                cleaned_text += line
                
    return cleaned_text.strip()


def get_ocr_text(img_path):
    # 1. Try RapidOCR (high accuracy, ONNX runtime, local execution)
    try:
        from rapidocr_onnxruntime import RapidOCR
        global _rapid_ocr_engine
        if '_rapid_ocr_engine' not in globals():
            _rapid_ocr_engine = RapidOCR()
            
        result, elapse = _rapid_ocr_engine(img_path)
        if result:
            ocr_lines = []
            for item in result:
                text_val = item[1].strip()
                if text_val:
                    ocr_lines.append(text_val)
            return "\n".join(ocr_lines)
    except Exception:
        pass

    # 2. Fallback to Tesseract-OCR if python bindings are missing/failed
    try:
        r_ocr = subprocess.run(
            ['tesseract', img_path, 'stdout', '-l', 'chi_sim+eng', '--psm', '3'],
            capture_output=True, text=True
        )
        return r_ocr.stdout.strip()
    except Exception:
        pass
        
    return ""


def run_ocr_translation():
    import os, tempfile
    
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
        tmp_img = f.name
    
    try:
        # 1. Capture screen area using maim
        r = subprocess.run(['maim', '-s', tmp_img], capture_output=True)
        if r.returncode != 0:
            return
        
        x, y = mouse_pos()
        win = None
        
        def start_ocr_process():
            nonlocal win
            
            # 2. Perform OCR (uses RapidOCR with a Tesseract fallback)
            text = get_ocr_text(tmp_img)
            if not text:
                GLib.idle_add(lambda: win.destroy() or Gtk.main_quit())
                return
            
            # 3. Format and join lines intelligently
            text = clean_ocr_text(text)
            if not should_translate(text):
                GLib.idle_add(lambda: win.destroy() or Gtk.main_quit())
                return
            
            # Switch view to loading state
            GLib.idle_add(win.update_text, "...")
            zh, _ = translate(text)
            
            # Write OCR Log for debugging
            log_ocr(text, zh)
            
            # Update to final translation and the recognized original text for speaker button
            GLib.idle_add(lambda: win.update_text(zh, text))
        
        # Instantly show "OCR-ing" popup in UI thread
        win = Popup("", "正在识别...", "", x, y)
        win.connect("destroy", lambda *_: Gtk.main_quit())
        
        # Async run OCR to prevent blocking UI rendering
        threading.Thread(target=start_ocr_process, daemon=True).start()
        Gtk.main()
    finally:
        if os.path.exists(tmp_img):
            try:
                os.unlink(tmp_img)
            except:
                pass


if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda *_: Gtk.main_quit())
    
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--ocr":
        run_ocr_translation()
    else:
        Daemon().start()
