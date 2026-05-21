"""Local random link picker for YouTube videos and other web links."""

from __future__ import annotations

import copy
import json
import random
import re
import shutil
import uuid
import webbrowser
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.error import URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

import tkinter as tk
from tkinter import filedialog, messagebox, ttk


APP_DIR = Path(__file__).resolve().parent
DATA_FILE = APP_DIR / "links.json"
STARTER_PACK_FILE = APP_DIR / "starter_videos.json"
BACKUP_DIR = APP_DIR / "backups"
ICON_FILE = APP_DIR / "favicon.ico"
SUPPORTED_SCHEMES = {"http", "https"}
BACKUP_LIMIT = 20
SHUFFLE_MODES = ("Discovery", "Least opened", "Surprise", "Favorites", "Any")
URL_PATTERN = re.compile(
    r"(?:https?://|www\.)[^\s<>'\"]+|(?:youtube\.com|youtu\.be)/[^\s<>'\"]+",
    re.IGNORECASE,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_text(value: str) -> str:
    return " ".join(value.strip().split())


def parse_tags(value: str | Iterable[str] | None) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        pieces = value.replace(";", ",").split(",")
    else:
        pieces = list(value)
    tags: list[str] = []
    seen: set[str] = set()
    for piece in pieces:
        tag = clean_text(str(piece)).lower()
        if tag and tag not in seen:
            tags.append(tag)
            seen.add(tag)
    return tags


def normalize_url(raw_url: str) -> str:
    url = raw_url.strip().strip("<>[]{}\"'")
    url = url.rstrip(".,;:")
    while url.endswith(")") and url.count("(") < url.count(")"):
        url = url[:-1]
    if not url:
        raise ValueError("Enter a link first.")

    lowered = url.lower()
    if "://" not in lowered:
        first_part = url.split("/", 1)[0]
        if lowered.startswith("www.") or "." in first_part:
            url = f"https://{url}"
        else:
            raise ValueError("Use a full web address such as https://youtu.be/...")

    parts = urlsplit(url)
    if parts.scheme.lower() not in SUPPORTED_SCHEMES or not parts.netloc:
        raise ValueError("Only http and https links are supported.")
    if not parts.hostname or "." not in parts.hostname:
        raise ValueError("That link does not include a valid host.")
    return url


def youtube_video_id(url: str) -> str | None:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    path_bits = [bit for bit in parts.path.split("/") if bit]

    if host == "youtu.be" and path_bits:
        return path_bits[0]
    if host.endswith("youtube.com") or host.endswith("youtube-nocookie.com"):
        if parts.path == "/watch":
            return parse_qs(parts.query).get("v", [None])[0]
        if len(path_bits) >= 2 and path_bits[0] in {"embed", "shorts", "live"}:
            return path_bits[1]
    return None


def infer_title(url: str) -> str:
    video_id = youtube_video_id(url)
    if video_id:
        return f"YouTube: {video_id}"

    parts = urlsplit(url)
    host = parts.hostname or "web link"
    path = parts.path.strip("/")
    if path:
        return f"{host} / {path[:60]}"
    return host


def display_date(value: str | None) -> str:
    if not value:
        return ""
    return value.replace("T", " ").replace("Z", "")[:16]


def shorten(value: str, limit: int = 110) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."


@dataclass
class VideoLink:
    id: str
    url: str
    title: str
    channel: str = ""
    tags: list[str] = field(default_factory=list)
    favorite: bool = False
    added_at: str = field(default_factory=utc_now)
    last_opened: str | None = None
    open_count: int = 0

    @classmethod
    def from_raw(cls, raw: object) -> "VideoLink":
        if isinstance(raw, str):
            return create_link(raw)
        if not isinstance(raw, dict):
            raise ValueError("Each link must be a URL string or object.")

        url = normalize_url(str(raw.get("url", "")))
        title = clean_text(str(raw.get("title") or "")) or infer_title(url)
        open_count = raw.get("open_count", 0)
        try:
            open_count = max(0, int(open_count))
        except (TypeError, ValueError):
            open_count = 0

        return cls(
            id=str(raw.get("id") or uuid.uuid4().hex),
            url=url,
            title=title,
            channel=clean_text(str(raw.get("channel") or raw.get("author") or "")),
            tags=parse_tags(raw.get("tags")),
            favorite=bool(raw.get("favorite", False)),
            added_at=str(raw.get("added_at") or utc_now()),
            last_opened=str(raw.get("last_opened")) if raw.get("last_opened") else None,
            open_count=open_count,
        )


def create_link(
    url: str,
    title: str = "",
    tags: str | Iterable[str] | None = None,
    channel: str = "",
) -> VideoLink:
    normalized = normalize_url(url)
    return VideoLink(
        id=uuid.uuid4().hex,
        url=normalized,
        title=clean_text(title) or infer_title(normalized),
        channel=clean_text(channel),
        tags=parse_tags(tags),
    )


def load_links(path: Path = DATA_FILE, *, strict: bool = True) -> list[VideoLink]:
    if not path.exists():
        return []

    try:
        with path.open("r", encoding="utf-8") as file:
            raw_data = json.load(file)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} is not valid JSON: {exc}") from exc

    if isinstance(raw_data, dict):
        raw_links = raw_data.get("links", [])
    else:
        raw_links = raw_data

    if not isinstance(raw_links, list):
        raise ValueError(f"{path.name} must contain a list of links.")

    links: list[VideoLink] = []
    seen_urls: set[str] = set()
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_links, start=1):
        try:
            link = VideoLink.from_raw(raw)
        except ValueError as exc:
            if strict:
                raise ValueError(f"{path.name} link #{index} is invalid: {exc}") from exc
            continue
        key = link.url.lower()
        if key in seen_urls:
            if strict:
                raise ValueError(f"{path.name} link #{index} duplicates an earlier URL.")
            continue
        while link.id in seen_ids:
            link.id = uuid.uuid4().hex
        seen_urls.add(key)
        seen_ids.add(link.id)
        links.append(link)
    return links


def backup_path_for(path: Path, timestamp: str | None = None) -> Path:
    stamp = timestamp or utc_now().replace(":", "").replace("-", "")
    return BACKUP_DIR / f"{path.stem}-{stamp}{path.suffix}.bak"


def create_backup(path: Path = DATA_FILE) -> Path | None:
    if not path.exists() or path.stat().st_size == 0:
        return None

    BACKUP_DIR.mkdir(exist_ok=True)
    backup_path = backup_path_for(path)
    shutil.copy2(path, backup_path)

    backups = sorted(
        BACKUP_DIR.glob(f"{path.stem}-*{path.suffix}.bak"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for old_backup in backups[BACKUP_LIMIT:]:
        old_backup.unlink(missing_ok=True)
    return backup_path


def save_links(links: list[VideoLink], path: Path = DATA_FILE, *, keep_backup: bool = False) -> None:
    payload = {
        "version": 1,
        "updated_at": utc_now(),
        "links": [asdict(link) for link in links],
    }
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")
    if keep_backup:
        create_backup(path)
    temp_path.replace(path)


def extract_urls(text: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in URL_PATTERN.findall(text):
        try:
            url = normalize_url(match)
        except ValueError:
            continue
        key = url.lower()
        if key not in seen:
            urls.append(url)
            seen.add(key)
    return urls


def filter_links(links: list[VideoLink], query: str = "", favorites_only: bool = False) -> list[VideoLink]:
    filtered = [link for link in links if not favorites_only or link.favorite]
    tokens = query.strip().lower().split()
    if not tokens:
        return filtered
    return [
        link
        for link in filtered
        if all(
            token in f"{link.title} {link.channel} {link.url} {' '.join(link.tags)}".lower()
            for token in tokens
        )
    ]


def sort_links(links: list[VideoLink], column: str, descending: bool = False) -> list[VideoLink]:
    def key(link: VideoLink) -> object:
        if column == "title":
            return link.title.lower()
        if column == "channel":
            return link.channel.lower()
        if column == "tags":
            return ", ".join(link.tags).lower()
        if column == "opens":
            return link.open_count
        if column == "last_opened":
            return link.last_opened or ""
        if column == "url":
            return link.url.lower()
        return link.title.lower()

    return sorted(links, key=key, reverse=descending)


def library_stats(links: list[VideoLink], shown: int | None = None) -> str:
    total = len(links)
    favorites = sum(1 for link in links if link.favorite)
    unopened = sum(1 for link in links if link.open_count == 0)
    tag_counts = Counter(tag for link in links for tag in link.tags)
    top_tags = ", ".join(tag for tag, _count in tag_counts.most_common(4)) or "no tags"
    shown_text = f"{shown} shown / " if shown is not None else ""
    return f"{shown_text}{total} saved | {favorites} favorites | {unopened} unopened | top tags: {top_tags}"


def choose_random_link(
    candidates: list[VideoLink],
    current_id: str | None = None,
    mode: str = "Discovery",
) -> VideoLink | None:
    if not candidates:
        return None

    pool = list(candidates)
    if mode == "Favorites":
        pool = [link for link in pool if link.favorite] or pool
    elif mode == "Discovery":
        unopened = [link for link in pool if link.open_count == 0]
        if unopened:
            pool = unopened
        else:
            min_open_count = min(link.open_count for link in pool)
            pool = [link for link in pool if link.open_count == min_open_count]
    elif mode == "Least opened":
        min_open_count = min(link.open_count for link in pool)
        pool = [link for link in pool if link.open_count == min_open_count]
    elif mode == "Surprise":
        if current_id and len(pool) > 1:
            pool = [link for link in pool if link.id != current_id] or pool
        weights = [(3 if link.favorite else 1) / (1 + link.open_count) for link in pool]
        return random.choices(pool, weights=weights, k=1)[0]

    if current_id and len(pool) > 1:
        pool = [link for link in pool if link.id != current_id] or pool
    return random.choice(pool)


def fetch_youtube_metadata(url: str, timeout: int = 8) -> dict[str, str]:
    if not youtube_video_id(url):
        return {}

    endpoint = "https://www.youtube.com/oembed?" + urlencode({"url": url, "format": "json"})
    request = Request(endpoint, headers={"User-Agent": "RandomYouTubeLinkPicker/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError):
        return {}

    return {
        "title": clean_text(str(payload.get("title", ""))),
        "channel": clean_text(str(payload.get("author_name", ""))),
        "thumbnail_url": clean_text(str(payload.get("thumbnail_url", ""))),
    }


class RandomLinkApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.links: list[VideoLink] = []
        self.load_error: str | None = None
        self.data_writable = True
        self.current_id: str | None = None

        self.current_title_var = tk.StringVar(value="No link selected")
        self.current_url_var = tk.StringVar(value="Add links or import from clipboard to begin.")
        self.url_var = tk.StringVar()
        self.title_var = tk.StringVar()
        self.channel_var = tk.StringVar()
        self.tags_var = tk.StringVar()
        self.search_var = tk.StringVar()
        self.status_var = tk.StringVar()
        self.stats_var = tk.StringVar()
        self.shuffle_mode_var = tk.StringVar(value=SHUFFLE_MODES[0])
        self.favorite_var = tk.BooleanVar(value=False)
        self.only_favorites_var = tk.BooleanVar(value=False)
        self.always_on_top_var = tk.BooleanVar(value=True)
        self.search_after_id: str | None = None
        self.sort_column = "title"
        self.sort_descending = False
        self.undo_links: list[VideoLink] | None = None
        self.undo_label = ""

        self._load_data()
        self._build_ui()
        self._bind_events()
        self.refresh_view()
        self.root.after(100, self._after_startup)

    def _load_data(self) -> None:
        try:
            self.links = load_links(DATA_FILE)
        except ValueError as exc:
            self.links = []
            self.load_error = str(exc)
            self.data_writable = False
            return
        if not DATA_FILE.exists():
            try:
                save_links(self.links, DATA_FILE)
            except OSError as exc:
                self.load_error = f"Could not create {DATA_FILE.name}: {exc}"
                self.data_writable = False

    def _build_ui(self) -> None:
        self.root.title("Random YouTube Link Picker")
        self.root.minsize(1040, 700)
        self.root.attributes("-topmost", self.always_on_top_var.get())

        if ICON_FILE.exists():
            try:
                self.root.iconbitmap(str(ICON_FILE))
            except tk.TclError:
                pass

        style = ttk.Style(self.root)
        style.configure("Current.TLabel", font=("Segoe UI", 13, "bold"))
        style.configure("Status.TLabel", padding=(6, 4))

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        self._build_menu()

        main = ttk.Frame(self.root, padding=12)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(3, weight=1)

        picker = ttk.LabelFrame(main, text="Current pick", padding=10)
        picker.grid(row=0, column=0, sticky="ew")
        picker.columnconfigure(0, weight=1)

        title_label = ttk.Label(
            picker,
            textvariable=self.current_title_var,
            style="Current.TLabel",
            wraplength=800,
        )
        title_label.grid(row=0, column=0, columnspan=5, sticky="ew", pady=(0, 4))

        url_label = ttk.Label(picker, textvariable=self.current_url_var, wraplength=800)
        url_label.grid(row=1, column=0, columnspan=5, sticky="ew", pady=(0, 8))

        self.open_button = ttk.Button(picker, text="Open", command=self.open_current)
        self.open_button.grid(row=2, column=0, sticky="w")
        self.random_button = ttk.Button(picker, text="Random", command=self.pick_random)
        self.random_button.grid(row=2, column=1, padx=(8, 0), sticky="w")
        ttk.Label(picker, text="Mode").grid(row=2, column=2, padx=(12, 6), sticky="w")
        self.shuffle_combo = ttk.Combobox(
            picker,
            textvariable=self.shuffle_mode_var,
            values=SHUFFLE_MODES,
            state="readonly",
            width=14,
        )
        self.shuffle_combo.grid(row=2, column=3, sticky="w")
        self.copy_button = ttk.Button(picker, text="Copy", command=self.copy_current)
        self.copy_button.grid(row=2, column=4, padx=(8, 0), sticky="w")
        self.favorite_check = ttk.Checkbutton(
            picker,
            text="Favorite",
            variable=self.favorite_var,
            command=self.toggle_current_favorite,
        )
        self.favorite_check.grid(row=2, column=5, padx=(12, 0), sticky="w")

        form = ttk.LabelFrame(main, text="Add or edit link", padding=10)
        form.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        ttk.Label(form, text="URL").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.url_entry = ttk.Entry(form, textvariable=self.url_var)
        self.url_entry.grid(row=0, column=1, columnspan=3, sticky="ew")

        ttk.Label(form, text="Title").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        ttk.Entry(form, textvariable=self.title_var).grid(row=1, column=1, sticky="ew", pady=(8, 0))
        ttk.Label(form, text="Channel").grid(row=1, column=2, sticky="w", padx=(12, 8), pady=(8, 0))
        ttk.Entry(form, textvariable=self.channel_var).grid(row=1, column=3, sticky="ew", pady=(8, 0))
        ttk.Label(form, text="Tags").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        ttk.Entry(form, textvariable=self.tags_var).grid(row=2, column=1, columnspan=3, sticky="ew", pady=(8, 0))

        button_row = ttk.Frame(form)
        button_row.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        self.save_button = ttk.Button(button_row, text="Save link", command=self.save_form)
        self.save_button.grid(row=0, column=0, sticky="w")
        self.clear_button = ttk.Button(button_row, text="Clear", command=self.clear_form)
        self.clear_button.grid(row=0, column=1, padx=(8, 0), sticky="w")
        self.delete_button = ttk.Button(button_row, text="Delete selected", command=self.delete_selected)
        self.delete_button.grid(row=0, column=2, padx=(8, 0), sticky="w")
        self.enrich_button = ttk.Button(button_row, text="Enrich selected", command=self.enrich_selected)
        self.enrich_button.grid(row=0, column=3, padx=(8, 0), sticky="w")

        tools = ttk.Frame(main)
        tools.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        tools.columnconfigure(1, weight=1)

        ttk.Label(tools, text="Search").grid(row=0, column=0, padx=(0, 8), sticky="w")
        self.search_entry = ttk.Entry(tools, textvariable=self.search_var)
        self.search_entry.grid(row=0, column=1, sticky="ew")
        ttk.Checkbutton(
            tools,
            text="Favorites only",
            variable=self.only_favorites_var,
            command=self.refresh_view,
        ).grid(row=0, column=2, padx=(8, 0), sticky="w")
        ttk.Checkbutton(
            tools,
            text="Always on top",
            variable=self.always_on_top_var,
            command=self.toggle_topmost,
        ).grid(row=0, column=3, padx=(8, 0), sticky="w")
        ttk.Button(tools, text="Import clipboard", command=self.import_clipboard).grid(
            row=1, column=1, pady=(8, 0), sticky="w"
        )
        ttk.Button(tools, text="Starter pack", command=self.import_starter_pack).grid(
            row=1, column=2, padx=(8, 0), pady=(8, 0), sticky="w"
        )
        ttk.Button(tools, text="Import file", command=self.import_file).grid(
            row=1, column=3, padx=(8, 0), pady=(8, 0), sticky="w"
        )
        ttk.Button(tools, text="Enrich shown", command=self.enrich_shown).grid(
            row=1, column=4, padx=(8, 0), pady=(8, 0), sticky="w"
        )
        ttk.Button(tools, text="Backup", command=self.backup_now).grid(
            row=1, column=5, padx=(8, 0), pady=(8, 0), sticky="w"
        )
        ttk.Button(tools, text="Export", command=self.export_links).grid(
            row=1, column=6, padx=(8, 0), pady=(8, 0), sticky="w"
        )

        table_frame = ttk.Frame(main)
        table_frame.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        columns = ("title", "channel", "tags", "opens", "last_opened", "url")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        for column, label in (
            ("title", "Title"),
            ("channel", "Channel"),
            ("tags", "Tags"),
            ("opens", "Opens"),
            ("last_opened", "Last opened"),
            ("url", "URL"),
        ):
            self.tree.heading(column, text=label, command=lambda value=column: self.sort_by(value))
        self.tree.column("title", width=260, minwidth=160)
        self.tree.column("channel", width=160, minwidth=100)
        self.tree.column("tags", width=150, minwidth=90)
        self.tree.column("opens", width=70, minwidth=60, anchor="center")
        self.tree.column("last_opened", width=130, minwidth=100)
        self.tree.column("url", width=320, minwidth=200)
        self.tree.grid(row=0, column=0, sticky="nsew")

        y_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        x_scroll.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        stats = ttk.Label(main, textvariable=self.stats_var, style="Status.TLabel")
        stats.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        status = ttk.Label(main, textvariable=self.status_var, style="Status.TLabel")
        status.grid(row=5, column=0, sticky="ew")

    def _build_menu(self) -> None:
        menu = tk.Menu(self.root)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Import from clipboard", command=self.import_clipboard)
        file_menu.add_command(label="Import starter pack", command=self.import_starter_pack)
        file_menu.add_command(label="Import from file...", command=self.import_file)
        file_menu.add_command(label="Export links...", command=self.export_links)
        file_menu.add_separator()
        file_menu.add_command(label="Backup now", command=self.backup_now)
        file_menu.add_command(label="Open backups folder", command=self.open_backups_folder)
        file_menu.add_command(label="Open data folder", command=self.open_data_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.destroy)
        menu.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menu, tearoff=False)
        edit_menu.add_command(label="Undo last library change", command=self.undo_last_change, accelerator="Ctrl+Z")
        edit_menu.add_command(label="Clear form", command=self.clear_form, accelerator="Esc")
        menu.add_cascade(label="Edit", menu=edit_menu)

        action_menu = tk.Menu(menu, tearoff=False)
        action_menu.add_command(label="Random", command=self.pick_random, accelerator="Ctrl+N")
        action_menu.add_command(label="Open current", command=self.open_current, accelerator="Ctrl+O")
        action_menu.add_command(label="Copy current", command=self.copy_current, accelerator="Ctrl+Shift+C")
        action_menu.add_command(label="Enrich selected", command=self.enrich_selected)
        action_menu.add_command(label="Enrich shown", command=self.enrich_shown)
        menu.add_cascade(label="Actions", menu=action_menu)
        self.root.configure(menu=menu)

    def _bind_events(self) -> None:
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.tree.bind("<Double-1>", lambda _event: self.open_current())
        self.tree.bind("<Delete>", lambda _event: self.delete_selected())
        self.search_var.trace_add("write", lambda *_args: self.schedule_refresh())
        self.root.bind("<Control-n>", lambda _event: self.pick_random())
        self.root.bind("<Control-o>", lambda _event: self.open_current())
        self.root.bind("<Control-l>", lambda _event: self.focus_url())
        self.root.bind("<Control-f>", lambda _event: self.focus_search())
        self.root.bind("<Control-z>", lambda _event: self.undo_last_change())
        self.root.bind("<Control-Shift-C>", lambda _event: self.copy_current())
        self.root.bind("<Escape>", lambda _event: self.clear_form())
        self.root.bind("<Return>", self.handle_enter)

    def _after_startup(self) -> None:
        if self.load_error:
            messagebox.showerror("Could not load links", self.load_error)
        if self.links:
            self.pick_random(show_message=False)
        else:
            self.update_actions()
            self.set_status(f"No links yet. Add a URL or import links. Data file: {DATA_FILE.name}")

    def set_status(self, message: str) -> None:
        self.status_var.set(message)

    def ensure_writable(self) -> bool:
        if self.data_writable:
            return True
        message = self.load_error or f"{DATA_FILE.name} is not writable."
        messagebox.showerror(
            "Local library is read-only",
            f"{message}\n\nFix or rename {DATA_FILE.name}, then restart the app.",
        )
        self.set_status(f"Cannot save until {DATA_FILE.name} is fixed.")
        return False

    def persist_links(
        self,
        next_links: list[VideoLink],
        *,
        undo_label: str = "library change",
        record_undo: bool = True,
    ) -> bool:
        if not self.ensure_writable():
            return False
        previous_links = copy.deepcopy(self.links)
        try:
            save_links(next_links, DATA_FILE, keep_backup=True)
        except OSError as exc:
            messagebox.showerror("Could not save links", str(exc))
            self.set_status("Save failed. No local library changes were written.")
            return False
        self.links = next_links
        if record_undo:
            self.undo_links = previous_links
            self.undo_label = undo_label
        return True

    def undo_last_change(self) -> None:
        if self.undo_links is None:
            self.set_status("Nothing to undo.")
            return
        restored = copy.deepcopy(self.undo_links)
        label = self.undo_label or "library change"
        self.undo_links = None
        self.undo_label = ""
        if not self.persist_links(restored, record_undo=False):
            return
        self.show_current(None)
        self.clear_form()
        self.refresh_view()
        self.set_status(f"Undid {label}.")

    def backup_now(self) -> None:
        try:
            backup_path = create_backup(DATA_FILE)
        except OSError as exc:
            messagebox.showerror("Backup failed", str(exc))
            return
        if backup_path:
            self.set_status(f"Backup created: {backup_path.name}")
        else:
            self.set_status("Nothing to back up yet.")

    def focus_url(self) -> None:
        self.url_entry.focus_set()
        self.url_entry.select_range(0, tk.END)

    def focus_search(self) -> None:
        self.search_entry.focus_set()
        self.search_entry.select_range(0, tk.END)

    def toggle_topmost(self) -> None:
        self.root.attributes("-topmost", self.always_on_top_var.get())

    def schedule_refresh(self) -> None:
        if self.search_after_id:
            self.root.after_cancel(self.search_after_id)
        self.search_after_id = self.root.after(150, self.refresh_view)

    def filtered_links(self) -> list[VideoLink]:
        links = filter_links(self.links, self.search_var.get(), self.only_favorites_var.get())
        return sort_links(links, self.sort_column, self.sort_descending)

    def sort_by(self, column: str) -> None:
        if self.sort_column == column:
            self.sort_descending = not self.sort_descending
        else:
            self.sort_column = column
            self.sort_descending = False
        self.refresh_view()

    def refresh_view(self) -> None:
        self.search_after_id = None
        selected = self.selected_id()
        filtered = self.filtered_links()
        if hasattr(self, "tree"):
            self.tree.delete(*self.tree.get_children())
            for link in filtered:
                marker = "*" if link.favorite else ""
                self.tree.insert(
                    "",
                    tk.END,
                    iid=link.id,
                    values=(
                        f"{marker}{link.title}",
                        link.channel,
                        ", ".join(link.tags),
                        link.open_count,
                        display_date(link.last_opened),
                        link.url,
                    ),
                )
            if selected and selected in self.tree.get_children():
                self.tree.selection_set(selected)
                self.tree.see(selected)

        shown = len(filtered)
        total = len(self.links)
        self.stats_var.set(library_stats(self.links, shown))
        self.set_status(f"{shown} shown / {total} saved in {DATA_FILE.name}")
        self.update_actions(filtered)

    def selected_id(self) -> str | None:
        if not hasattr(self, "tree"):
            return None
        selection = self.tree.selection()
        return selection[0] if selection else None

    def selected_link(self) -> VideoLink | None:
        selected = self.selected_id()
        return self.find_link(selected) if selected else None

    def current_link(self) -> VideoLink | None:
        return self.find_link(self.current_id) if self.current_id else None

    def find_link(self, link_id: str | None) -> VideoLink | None:
        if not link_id:
            return None
        return next((link for link in self.links if link.id == link_id), None)

    def find_by_url(self, url: str) -> VideoLink | None:
        key = url.lower()
        return next((link for link in self.links if link.url.lower() == key), None)

    def select_link(self, link_id: str) -> None:
        if link_id in self.tree.get_children():
            self.tree.selection_set(link_id)
            self.tree.focus(link_id)
            self.tree.see(link_id)

    def show_current(self, link: VideoLink | None) -> None:
        if not link:
            self.current_id = None
            self.current_title_var.set("No link selected")
            self.current_url_var.set("Add links or import from clipboard to begin.")
            self.favorite_var.set(False)
            return

        self.current_id = link.id
        self.current_title_var.set(link.title)
        self.current_url_var.set(shorten(link.url))
        self.favorite_var.set(link.favorite)

    def on_tree_select(self, _event: tk.Event) -> None:
        link = self.selected_link()
        if not link:
            self.update_actions()
            return
        self.show_current(link)
        self.url_var.set(link.url)
        self.title_var.set(link.title)
        self.channel_var.set(link.channel)
        self.tags_var.set(", ".join(link.tags))
        self.update_actions()

    def update_actions(self, filtered: list[VideoLink] | None = None) -> None:
        has_current = self.current_link() is not None
        has_selected = self.selected_link() is not None
        has_filtered = bool(filtered if filtered is not None else self.filtered_links())

        self.open_button.state(["!disabled"] if has_current else ["disabled"])
        self.copy_button.state(["!disabled"] if has_current else ["disabled"])
        self.favorite_check.state(["!disabled"] if has_current else ["disabled"])
        self.random_button.state(["!disabled"] if has_filtered else ["disabled"])
        self.delete_button.state(["!disabled"] if has_selected else ["disabled"])
        self.enrich_button.state(["!disabled"] if has_selected else ["disabled"])

    def clear_form(self) -> None:
        self.url_var.set("")
        self.title_var.set("")
        self.channel_var.set("")
        self.tags_var.set("")
        if self.tree.selection():
            self.tree.selection_remove(self.tree.selection())
        self.update_actions()
        self.focus_url()

    def handle_enter(self, event: tk.Event) -> None:
        focus = self.root.focus_get()
        if focus in {self.url_entry, self.search_entry}:
            self.save_form() if focus == self.url_entry else self.pick_random()
            return
        if focus == self.tree:
            self.open_current()

    def save_form(self) -> None:
        try:
            url = normalize_url(self.url_var.get())
        except ValueError as exc:
            messagebox.showwarning("Invalid link", str(exc))
            self.focus_url()
            return

        title = clean_text(self.title_var.get()) or infer_title(url)
        tags = parse_tags(self.tags_var.get())
        selected_id = self.selected_id()
        next_links = copy.deepcopy(self.links)
        selected = next((link for link in next_links if link.id == selected_id), None)
        duplicate = next((link for link in next_links if link.url.lower() == url.lower()), None)
        if duplicate and (not selected or duplicate.id != selected.id):
            self.select_link(duplicate.id)
            messagebox.showinfo("Already saved", "That link is already in your list.")
            return

        if selected:
            selected.url = url
            selected.title = title
            selected.tags = tags
            link = selected
        else:
            link = create_link(url, title, tags)
            next_links.append(link)

        if not self.persist_links(next_links):
            return
        self.refresh_view()
        self.select_link(link.id)
        self.show_current(link)
        self.set_status(f"Saved: {link.title}")

    def delete_selected(self) -> None:
        link = self.selected_link()
        if not link:
            return
        if not messagebox.askyesno("Delete link", f"Delete '{link.title}'?"):
            return

        next_links = [copy.deepcopy(item) for item in self.links if item.id != link.id]
        if not self.persist_links(next_links):
            return
        if self.current_id == link.id:
            self.show_current(None)
        self.clear_form()
        self.refresh_view()
        self.set_status(f"Deleted: {link.title}")

    def pick_random(self, show_message: bool = True) -> None:
        candidates = self.filtered_links()
        if not candidates:
            self.show_current(None)
            if show_message:
                messagebox.showinfo("No links", "No links match the current filter.")
            self.update_actions()
            return

        unopened = [link for link in candidates if link.open_count == 0]
        pool = unopened or candidates
        if self.current_id and len(pool) > 1:
            pool = [link for link in pool if link.id != self.current_id] or pool

        link = random.choice(pool)
        self.show_current(link)
        self.select_link(link.id)
        self.set_status(f"Picked: {link.title}")
        self.update_actions()

    def open_current(self) -> None:
        link = self.current_link() or self.selected_link()
        if not link:
            return
        try:
            opened = webbrowser.open_new_tab(link.url)
        except webbrowser.Error as exc:
            messagebox.showerror("Could not open link", str(exc))
            return

        next_links = copy.deepcopy(self.links)
        saved_link = next((item for item in next_links if item.id == link.id), None)
        if not saved_link:
            return
        saved_link.open_count += 1
        saved_link.last_opened = utc_now()
        if not self.persist_links(next_links):
            return
        self.refresh_view()
        self.select_link(saved_link.id)
        if not opened:
            self.set_status("The link was sent to the browser, but no browser confirmed it opened.")
        else:
            self.set_status(f"Opened: {saved_link.title}")

    def copy_current(self) -> None:
        link = self.current_link()
        if not link:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(link.url)
        self.set_status("Copied current link to clipboard.")

    def toggle_current_favorite(self) -> None:
        link = self.current_link() or self.selected_link()
        if not link:
            return
        next_links = copy.deepcopy(self.links)
        saved_link = next((item for item in next_links if item.id == link.id), None)
        if not saved_link:
            return
        saved_link.favorite = self.favorite_var.get()
        if not self.persist_links(next_links):
            return
        self.refresh_view()
        self.select_link(saved_link.id)
        self.set_status(("Favorited" if saved_link.favorite else "Unfavorited") + f": {saved_link.title}")

    def import_clipboard(self) -> None:
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            messagebox.showinfo("Clipboard empty", "The clipboard does not contain text.")
            return
        self.add_urls(extract_urls(text), "clipboard")

    def import_file(self) -> None:
        filename = filedialog.askopenfilename(
            title="Import links",
            filetypes=[
                ("Link files", "*.json *.txt *.csv *.md"),
                ("JSON files", "*.json"),
                ("Text files", "*.txt *.csv *.md"),
                ("All files", "*.*"),
            ],
        )
        if not filename:
            return

        path = Path(filename)
        try:
            if path.suffix.lower() == ".json":
                imported_links = load_links(path, strict=False)
                self.merge_links(imported_links)
            else:
                text = path.read_text(encoding="utf-8", errors="replace")
                self.add_urls(extract_urls(text), path.name)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Import failed", str(exc))

    def export_links(self) -> None:
        filename = filedialog.asksaveasfilename(
            title="Export links",
            initialfile="links-export.json",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not filename:
            return
        try:
            save_links(self.links, Path(filename))
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc))
            return
        self.set_status(f"Exported {len(self.links)} links.")

    def open_data_folder(self) -> None:
        webbrowser.open(DATA_FILE.parent.as_uri())

    def add_urls(self, urls: list[str], source: str) -> None:
        added: list[VideoLink] = []
        next_links = copy.deepcopy(self.links)
        existing = {link.url.lower() for link in next_links}
        for url in urls:
            if url.lower() in existing:
                continue
            link = create_link(url, tags=[source] if source not in {"clipboard"} else None)
            next_links.append(link)
            added.append(link)
            existing.add(url.lower())

        if not added:
            messagebox.showinfo("No new links", "No new valid links were found.")
            return

        if not self.persist_links(next_links):
            return
        self.refresh_view()
        self.select_link(added[-1].id)
        self.show_current(added[-1])
        self.set_status(f"Imported {len(added)} new link(s) from {source}.")

    def merge_links(self, imported_links: list[VideoLink]) -> None:
        added: list[VideoLink] = []
        next_links = copy.deepcopy(self.links)
        existing_urls = {link.url.lower() for link in next_links}
        existing_ids = {link.id for link in next_links}

        for link in imported_links:
            if link.url.lower() in existing_urls:
                continue
            imported_link = copy.deepcopy(link)
            while imported_link.id in existing_ids:
                imported_link.id = uuid.uuid4().hex
            next_links.append(imported_link)
            added.append(imported_link)
            existing_urls.add(imported_link.url.lower())
            existing_ids.add(imported_link.id)

        if not added:
            messagebox.showinfo("No new links", "No new links were imported.")
            return

        if not self.persist_links(next_links):
            return
        self.refresh_view()
        self.select_link(added[-1].id)
        self.show_current(added[-1])
        self.set_status(f"Imported {len(added)} new link(s).")


def main() -> None:
    root = tk.Tk()
    app = RandomLinkApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
