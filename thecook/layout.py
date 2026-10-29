"""Tk layout containers that fit small desktop windows."""
import tkinter as tk
from tkinter import ttk


class AutoScrollbar(ttk.Scrollbar):
    """A grid-managed scrollbar that only occupies space when scrolling is needed."""

    def set(self, first, last):
        super().set(first, last)
        needed = float(first) > 0 or float(last) < 1
        visible = self.winfo_manager() == "grid"
        if needed and not visible:
            self.grid()
        elif visible and not needed:
            self.grid_remove()


class FlowFrame(ttk.Frame):
    """Place controls left to right, wrapping complete controls to new rows."""

    def __init__(self, parent, item_anchor="center", **kwargs):
        super().__init__(parent, **kwargs)
        self.item_anchor = item_anchor
        self.items = []
        self._pending = None
        self._positions = None
        self.bind("<Configure>", self._schedule)

    def add(self, widget):
        self.items.append(widget)
        widget.bind("<Configure>", self._schedule, add="+")
        self._schedule()

    def _schedule(self, _=None):
        if self._pending is None:
            self._pending = self.after_idle(self._arrange)

    def _arrange(self):
        self._pending = None
        width = max(1, self.winfo_width())
        row = column = used = 0
        positions = []
        for widget in self.items:
            needed = widget.winfo_reqwidth() + 12
            if column and used + needed > width:
                row += 1
                column = used = 0
            positions.append((row, column))
            used += needed
            column += 1
        if positions != self._positions:
            self._positions = positions
            # Rows may contain differently sized controls; separate row frames
            # prevent grid column widths from accumulating across wrapped rows.
            for child in getattr(self, "_rows", []):
                child.pack_forget()
            self._rows = getattr(self, "_rows", [])
            count = row + 1 if self.items else 0
            while len(self._rows) < count:
                self._rows.append(ttk.Frame(self, style=self.cget("style") or "TFrame"))
            for frame in self._rows[:count]:
                frame.pack(fill="x")
            for widget, (row, _) in zip(self.items, positions):
                widget.pack_forget()
                widget.pack(in_=self._rows[row], side="left", anchor=self.item_anchor,
                            padx=(0, 12), pady=2)
                widget.lift()


class ScrollPage(ttk.Frame):
    """Constrain content to viewport width and scroll excess height."""

    def __init__(self, parent, background):
        super().__init__(parent)
        self._pending = None
        self.canvas = tk.Canvas(self, bg=background, highlightthickness=0, yscrollincrement=24)
        self.scrollbar = AutoScrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.scrollbar.grid_remove()
        self.content = ttk.Frame(self.canvas)
        self.window = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.canvas.bind("<Configure>", self._resize)
        self.content.bind("<Configure>", self._content_changed)
        top = self.winfo_toplevel()
        top.bind("<MouseWheel>", self._wheel, add="+")
        top.bind("<Button-4>", self._wheel, add="+")
        top.bind("<Button-5>", self._wheel, add="+")
        top.bind("<FocusIn>", self._focus, add="+")
        top.bind("<Configure>", self._layout_changed, add="+")

    def _layout_changed(self, event):
        # A child's requested height can change while the canvas still forces
        # the content to its old height, so content Configure alone is insufficient.
        if self._contains(event.widget) and self._pending is None:
            self._pending = self.after_idle(self._sync)

    def _sync(self):
        self._pending = None
        self._content_changed()

    def _resize(self, event):
        self.canvas.itemconfigure(self.window, width=event.width)
        self._content_changed()

    def _content_changed(self, _=None):
        height = max(self.content.winfo_reqheight(), self.canvas.winfo_height())
        self.canvas.itemconfigure(self.window, height=height)
        self.canvas.configure(scrollregion=(0, 0, self.canvas.winfo_width(), height))

    def _contains(self, widget):
        while isinstance(widget, tk.Misc):
            if widget == self.content:
                return True
            widget = widget.master
        return False

    def _wheel(self, event):
        if not self._contains(event.widget):
            return
        # Preserve scrolling and selection inside text, tables and comboboxes.
        if event.widget.winfo_class() in ("Text", "Treeview", "TCombobox", "Scrollbar", "TScrollbar"):
            return
        if event.num == 4:
            units = -1
        elif event.num == 5:
            units = 1
        else:
            units = -int(event.delta / 120) if abs(event.delta) >= 120 else (-1 if event.delta > 0 else 1)
        self.canvas.yview_scroll(units, "units")

    def _focus(self, event):
        widget = event.widget
        if not self._contains(widget):
            return
        top = widget.winfo_rooty() - self.content.winfo_rooty()
        bottom = top + widget.winfo_height()
        visible_top = self.canvas.canvasy(0)
        visible_bottom = visible_top + self.canvas.winfo_height()
        height = max(1, self.content.winfo_height())
        if top < visible_top:
            self.canvas.yview_moveto(max(0, top - 8) / height)
        elif bottom > visible_bottom:
            self.canvas.yview_moveto((bottom + 8 - self.canvas.winfo_height()) / height)
