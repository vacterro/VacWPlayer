import tkinter as tk
from tkinter import ttk

# Vintage Dark Golden Win95 Tokens
TOKENS = {
    "background": "#1A1810",
    "backgroundSoft": "#232018",
    "surface": "#332E22",
    "surfaceRaised": "#3D372A",
    "surfaceAlt": "#453D30",
    "borderDark": "#100E08",
    "borderHighlight": "#F0D060",
    "borderMuted": "#5A5040",
    "textPrimary": "#D4C89A",
    "textSecondary": "#9C9371",
    "textMuted": "#6E674E",
    "accentTeal": "#008080",
    "accentTealDeep": "#004C4C",
    "success": "#4A7A20",
    "warning": "#7A7A20",
    "danger": "#7A2020",
    "dangerText": "#D66464",
    "selection": "#3D372A",
    "compareBack": "#14120C",
    "link": "#F0D060",
}

FONT_MAIN = ("Verdana", 10)
FONT_SM = ("Verdana", 9)
FONT_BOLD = ("Verdana", 10, "bold")

class VintageRaised(tk.Frame):
    def __init__(self, parent, bg_color=TOKENS["surfaceRaised"], border_width=1, **kwargs):
        super().__init__(parent, bg=TOKENS["borderDark"], bd=0, highlightthickness=0, highlightbackground=TOKENS["background"], highlightcolor=TOKENS["background"], **kwargs)
        self.inner = tk.Frame(self, bg=TOKENS["borderHighlight"], bd=0, highlightthickness=0, highlightbackground=TOKENS["background"], highlightcolor=TOKENS["background"])
        self.inner.pack(fill="both", expand=True, padx=(0, border_width), pady=(0, border_width))
        self.content = tk.Frame(self.inner, bg=bg_color, bd=0, highlightthickness=0, highlightbackground=TOKENS["background"], highlightcolor=TOKENS["background"])
        self.content.pack(fill="both", expand=True, padx=(border_width, 0), pady=(border_width, 0))

class VintageSunken(tk.Frame):
    def __init__(self, parent, bg_color=TOKENS["surface"], border_width=1, **kwargs):
        super().__init__(parent, bg=TOKENS["borderHighlight"], bd=0, highlightthickness=0, highlightbackground=TOKENS["background"], highlightcolor=TOKENS["background"], **kwargs)
        self.inner = tk.Frame(self, bg=TOKENS["borderDark"], bd=0, highlightthickness=0, highlightbackground=TOKENS["background"], highlightcolor=TOKENS["background"])
        self.inner.pack(fill="both", expand=True, padx=(0, border_width), pady=(0, border_width))
        self.content = tk.Frame(self.inner, bg=bg_color, bd=0, highlightthickness=0, highlightbackground=TOKENS["background"], highlightcolor=TOKENS["background"])
        self.content.pack(fill="both", expand=True, padx=(border_width, 0), pady=(border_width, 0))

class VintageButton(VintageRaised):
    """Raised bevel + label. Press swaps the two bevel colours in place instead
    of swapping in a whole second widget stack: identical Win95 look, but 4
    Win32 child windows per button instead of 8, and press/release no longer
    re-runs the geometry manager (that repack made the label jump)."""

    def __init__(self, parent, text, command=None, width=None, **kwargs):
        self.bg_normal = TOKENS["surfaceRaised"]
        self.bg_hover = TOKENS["surfaceAlt"]
        self.bg_pressed = TOKENS["surface"]
        super().__init__(parent, bg_color=self.bg_normal, **kwargs)

        self.command = command
        self.label = tk.Label(self.content, text=text, font=FONT_MAIN,
                              bg=self.bg_normal, fg=TOKENS["textPrimary"])
        if width:
            self.label.config(width=width)
        self.label.pack(padx=2, pady=1)

        self._pressed = False
        self._current_bg = None
        self._paint(self.bg_normal)

        for w in (self, self.inner, self.content, self.label):
            w.bind("<Enter>", self._on_hover)
            w.bind("<Leave>", self._on_leave)
            w.bind("<ButtonPress-1>", self._on_press)
            w.bind("<ButtonRelease-1>", self._on_release)

    def _set_bevel(self, pressed):
        # raised = light top-left / dark bottom-right; sunken inverts the pair.
        if pressed:
            self.config(bg=TOKENS["borderHighlight"])
            self.inner.config(bg=TOKENS["borderDark"])
        else:
            self.config(bg=TOKENS["borderDark"])
            self.inner.config(bg=TOKENS["borderHighlight"])

    def _paint(self, bg):
        if getattr(self, "_current_bg", None) != bg:
            self.content.config(bg=bg)
            self.label.config(bg=bg)
            self._current_bg = bg

    def _on_hover(self, e):
        if not self._pressed:
            self._paint(self.bg_hover)

    def _on_leave(self, e):
        # Ignore leave events that just crossed into a child widget
        try:
            x = self.winfo_pointerx() - self.winfo_rootx()
            y = self.winfo_pointery() - self.winfo_rooty()
            if 0 <= x < self.winfo_width() and 0 <= y < self.winfo_height():
                return
        except tk.TclError:
            pass

        self._set_bevel(False)
        self._paint(self.bg_normal)
        if self._pressed:
            self._pressed = False
            self.label.pack_configure(padx=2, pady=1)

    def _on_press(self, e):
        self._pressed = True
        self._set_bevel(True)
        self._paint(self.bg_pressed)
        self.label.pack_configure(padx=(3, 1), pady=(2, 0))  # 1px label shift

    def _on_release(self, e):
        if not self._pressed:
            return
        self._pressed = False
        self._set_bevel(False)
        self._paint(self.bg_hover)
        self.label.pack_configure(padx=2, pady=1)
        if self.command:
            try:
                x = self.winfo_pointerx() - self.winfo_rootx()
                y = self.winfo_pointery() - self.winfo_rooty()
                if 0 <= x < self.winfo_width() and 0 <= y < self.winfo_height():
                    self.command()
            except tk.TclError:
                pass

class VintageLabel(tk.Label):
    def __init__(self, parent, text, bg=TOKENS["background"], fg=TOKENS["textPrimary"], font=FONT_MAIN, **kwargs):
        super().__init__(parent, text=text, bg=bg, fg=fg, font=font, **kwargs)

class VintageEntry(VintageSunken):
    def __init__(self, parent, textvariable=None, width=20, bg_color=TOKENS["compareBack"], **kwargs):
        super().__init__(parent, bg_color=bg_color, **kwargs)
        self.entry = tk.Entry(self.content, textvariable=textvariable, bg=bg_color,
                              fg=TOKENS["textPrimary"], font=FONT_MAIN, bd=0, highlightthickness=0,
                              highlightbackground=TOKENS["background"], highlightcolor=TOKENS["background"],
                              insertbackground=TOKENS["textPrimary"], width=width)
        self.entry.pack(fill="both", expand=True, padx=1, pady=0)


def make_check(parent, text, var):
    """Single shared Checkbutton factory (styling owned by theme.py)."""
    return tk.Checkbutton(
        parent, text=text, variable=var, bg=TOKENS["background"],
        fg=TOKENS["textPrimary"], activebackground=TOKENS["background"],
        activeforeground=TOKENS["textPrimary"], selectcolor=TOKENS["compareBack"],
        font=FONT_SM, highlightthickness=0, bd=0)


class VintageNotebook(tk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=TOKENS["background"], **kwargs)
        
        self.tab_frame = tk.Frame(self, bg=TOKENS["background"])
        self.tab_frame.pack(side="top", fill="x")
        
        self.content_frame = tk.Frame(self, bg=TOKENS["background"])
        self.content_frame.pack(side="top", fill="both", expand=True, pady=(2, 0))
        
        self._tabs = []
        self._buttons = {}
        self._active = None

    def _resolve(self, tab_id):
        if tab_id is None:
            return None
        if isinstance(tab_id, int):
            if 0 <= tab_id < len(self._tabs):
                return self._tabs[tab_id]
            return None
        if str(tab_id) == "end":
            return len(self._tabs)
        for w in self._tabs:
            if str(w) == str(tab_id):
                return w
        return None

    def add(self, child, text=""):
        self.insert("end", child, text=text)

    def insert(self, pos, child, text=""):
        idx = len(self._tabs)
        if pos != "end":
            target = self._resolve(pos)
            if target in self._tabs:
                idx = self._tabs.index(target)
            
        self._tabs.insert(idx, child)
        btn = VintageButton(self.tab_frame, text=text,
                            command=lambda w=child: self.select(w))
        self._buttons[child] = btn
        self._redraw_tabs()
        if self._active is None:
            self.select(child)

    def forget(self, tab_id):
        w = self._resolve(tab_id)
        if not w:
            return
        if w in self._tabs:
            self._tabs.remove(w)
        btn = self._buttons.pop(w, None)
        if btn:
            btn.destroy()
        w.pack_forget()
        self._redraw_tabs()
        if self._active == w:
            self._active = None
            if self._tabs:
                self.select(self._tabs[0])

    def select(self, tab_id=None):
        if tab_id is None:
            return str(self._active) if self._active else ""
        w = self._resolve(tab_id)
        if w and w in self._tabs:
            if self._active and self._active != w:
                self._active.pack_forget()
                ob = self._buttons.get(self._active)
                if ob:
                    ob.bg_normal = TOKENS["surfaceRaised"]
                    ob._paint(ob.bg_normal)
            
            self._active = w
            nb = self._buttons.get(w)
            if nb:
                nb.bg_normal = TOKENS["borderDark"]
                nb._paint(nb.bg_normal)
            
            w.pack(in_=self.content_frame, fill="both", expand=True)
            self.event_generate("<<NotebookTabChanged>>")
            
    def tabs(self):
        return [str(w) for w in self._tabs]

    def nametowidget(self, name):
        return self._resolve(name)

    def tab(self, tab_id, text=None, **kwargs):
        w = self._resolve(tab_id)
        if not w:
            return
        if text is not None:
            btn = self._buttons.get(w)
            if btn:
                btn.label.config(text=text)

    def index(self, tab_id):
        w = self._resolve(tab_id)
        if w in self._tabs:
            return self._tabs.index(w)
        return -1 if isinstance(tab_id, int) else len(self._tabs)

    def _redraw_tabs(self):
        for w in self.tab_frame.winfo_children():
            w.pack_forget()
        for child in self._tabs:
            btn = self._buttons.get(child)
            if btn:
                btn.pack(side="left", padx=0)


def apply_base_theme(root):
    root.config(bg=TOKENS["background"])
    style = ttk.Style()
    style.theme_use('default')
    # Use standard Vintage colors for notebook
    style.configure("TNotebook", background=TOKENS["background"], borderwidth=0)
    style.configure("TNotebook.Tab", background=TOKENS["surfaceRaised"], foreground=TOKENS["textPrimary"], 
                    padding=[4, 1], font=FONT_SM, borderwidth=0)
    style.map("TNotebook.Tab", background=[("selected", TOKENS["surface"])])
    style.configure("TCombobox", background=TOKENS["surfaceRaised"], foreground=TOKENS["textPrimary"],
                    fieldbackground=TOKENS["compareBack"], arrowcolor=TOKENS["textPrimary"],
                    selectbackground=TOKENS["selection"], selectforeground=TOKENS["textPrimary"],
                    font=FONT_SM, padding=2)
    style.map("TCombobox", fieldbackground=[("readonly", TOKENS["compareBack"])],
              background=[("active", TOKENS["surfaceAlt"])])
    root.option_add("*TCombobox*Listbox.background", TOKENS["surface"])
    root.option_add("*TCombobox*Listbox.foreground", TOKENS["textPrimary"])
    root.option_add("*TCombobox*Listbox.selectBackground", TOKENS["selection"])
    root.option_add("*TCombobox*Listbox.selectForeground", TOKENS["textPrimary"])
    root.option_add("*TCombobox*Listbox.font", FONT_SM)
