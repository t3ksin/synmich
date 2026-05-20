"""Placeholder view for tabs not yet implemented in the MVP."""

from __future__ import annotations

import customtkinter as ctk

from synmich.gui import widgets as W


class PlaceholderView(ctk.CTkFrame):
    def __init__(self, parent, title: str, note: str = ""):
        super().__init__(parent, fg_color=W.CONTENT)
        box = ctk.CTkFrame(self, fg_color="transparent")
        box.place(relx=0.5, rely=0.45, anchor="center")
        ctk.CTkLabel(box, text=title, font=W.font(22, "bold"),
                     text_color=W.TEXT).pack()
        ctk.CTkLabel(box, text=note or "Coming soon",
                     font=W.font(13), text_color=W.MUTED).pack(pady=(6, 0))
