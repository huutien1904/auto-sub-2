"""Video Translator VI — Entry point."""

import sys
import os

# Ensure the app directory is in the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import customtkinter as ctk
from app_window import VideoTranslatorApp

if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    app = VideoTranslatorApp()
    app.mainloop()
