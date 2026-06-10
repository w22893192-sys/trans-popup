#!/usr/bin/python3
"""trans-popup — select text in terminal → Chinese translation popup"""

import subprocess, threading, time, re, signal, json
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

def is_english(text):
    if not text or len(text.split()) > 80:
        return False
    ascii_alpha = sum(1 for c in text if c.isascii() and c.isalpha())
    total_alpha = sum(1 for c in text if c.isalpha())
    return total_alpha > 0 and ascii_alpha / total_alpha > 0.7

_cache = {}

def translate(text):
    key = text.lower().strip()
    if key in _cache:
        return _cache[key]
    result = _translate_api(text)
    _cache[key] = result
    if len(_cache) > 500:
        for k in list(_cache)[:100]:
            del _cache[k]
    return result

def _translate_api(text):
    try:
        url = (f"https://translate.googleapis.com/translate_a/single"
               f"?client=gtx&sl=en&tl=zh-CN&dt=t&q={quote(text)}")
        with urlopen(url, timeout=8) as r:
            data = json.loads(r.read())
        zh = "".join(seg[0] for seg in data[0] if seg[0])
        return zh or "—", ""
    except:
        return "—", ""

def speak(text):
    try:
        from gtts import gTTS
        import tempfile, os
        tts = gTTS(text=text, lang='en', slow=True)
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
            tmp = f.name
        tts.save(tmp)
        subprocess.run(['ffplay', '-nodisp', '-autoexit', '-loglevel', 'quiet', tmp])
        os.unlink(tmp)
    except Exception:
        subprocess.Popen(['spd-say', '-l', 'en', text],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def mouse_pos():
    try:
        ptr = Gdk.Display.get_default().get_default_seat().get_pointer()
        _, x, y = ptr.get_position()
        return x, y
    except:
        return 300, 300

def make_speaker_icon(orig):
    da = Gtk.DrawingArea()
    da.set_size_request(22, 22)

    def draw(widget, cr):
        cr.set_source_rgb(1, 1, 1)
        cr.set_line_width(1.8)
        cr.set_line_cap(1)
        cr.set_line_join(1)
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
               lambda *_: threading.Thread(target=speak, args=(orig,), daemon=True).start() or True)
    return eb


class Popup(Gtk.Window):
    def __init__(self, orig, zh, pron, x, y):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
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

        trans_lbl = Gtk.Label(label=zh)
        trans_lbl.set_name("trans")
        trans_lbl.set_halign(Gtk.Align.START)
        trans_lbl.set_line_wrap(True)
        trans_lbl.set_max_width_chars(36)
        row.pack_start(trans_lbl, True, True, 0)
        row.pack_end(make_speaker_icon(orig), False, False, 0)

        card.add(row)
        self.add(card)

        sw = screen.get_width()
        sh = screen.get_height()
        self.move(min(x + 16, sw - 320), min(y + 36, sh - 100))

        GLib.timeout_add(5000, lambda: self.destroy() or False)
        self.show_all()


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
            if text == self.last or not is_english(text):
                continue
            self.last = text
            x, y = mouse_pos()
            fut = {}
            t = text
            threading.Thread(target=lambda: fut.update(
                zip(('zh','pron'), translate(t))), daemon=True).start()
            time.sleep(0.12)
            if get_selection() != text or mouse_held():
                continue
            deadline = time.time() + 10
            while 'zh' not in fut and time.time() < deadline:
                time.sleep(0.05)
            if 'zh' in fut:
                GLib.idle_add(self._show, text, fut['zh'], fut.get('pron',''), x, y)

    def _show(self, orig, zh, pron, x, y):
        if self.popup:
            try: self.popup.destroy()
            except: pass
        self.popup = Popup(orig, zh, pron, x, y)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda *_: Gtk.main_quit())
    Daemon().start()
