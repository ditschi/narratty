"""Pydantic models for ``.narratty.yaml``.

Every model forbids unknown keys, so typos surface as validation errors instead
of being silently ignored.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Discriminator,
    Field,
    NonNegativeInt,
    StringConstraints,
    Tag,
    WithJsonSchema,
    field_validator,
    model_validator,
)

SCENE_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]*$"
HOST_PORT_PATTERN = r"^[A-Za-z0-9.-]+:[0-9]{1,5}$"

# Special keys VHS understands (optionally followed by a repeat count, e.g. "Down 3").
# VHS has no Home or End.
VHS_KEYS = (
    "Backspace",
    "Delete",
    "Down",
    "Enter",
    "Escape",
    "Insert",
    "Left",
    "PageDown",
    "PageUp",
    "Right",
    "Space",
    "Tab",
    "Up",
)
_KEY_PATTERN = re.compile(rf"^({'|'.join(VHS_KEYS)})( [1-9][0-9]*)?$", re.IGNORECASE)
_KEY_NAMES = {name.lower(): name for name in VHS_KEYS}

DURATION_PATTERN = r"^[0-9]+(\.[0-9]+)?(ms|s|m)$"
_DURATION = re.compile(DURATION_PATTERN)
_UNIT_MS = {"ms": 1, "s": 1000, "m": 60_000}


def to_ms(value: Any) -> Any:
    """``"1.5s"``, ``"800ms"`` or ``"2m"`` as milliseconds; anything else is passed on."""
    if isinstance(value, str) and (match := _DURATION.match(value.strip())):
        number = value.strip()[: match.start(2)]
        return round(float(number) * _UNIT_MS[match.group(2)])
    return value


# Milliseconds, written as a number or as a duration string ("1.5s", "800ms", "2m").
Duration = Annotated[
    int,
    BeforeValidator(to_ms),
    WithJsonSchema(
        {
            "anyOf": [
                {"type": "integer", "minimum": 0, "description": "Milliseconds"},
                {"type": "string", "pattern": DURATION_PATTERN, "description": "e.g. 1.5s, 800ms, 2m"},
            ]
        }
    ),
]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ── actions ───────────────────────────────────────────────────────────────────


class TypeCommand(_Model):
    """Type text at the scene's typing speed without pressing Enter (use ``run`` for commands)."""

    type_command: str = Field(min_length=1)


ExpectExit = Literal["success", "failure", "any"]


class Run(_Model):
    """Type a command, press Enter, then pause for ``timing.run_hold_ms``."""

    run: str = Field(min_length=1)
    expect_exit: ExpectExit | None = Field(
        None, description="Exit code of this command: success, failure or any; overrides the scene's."
    )


class Enter(_Model):
    """Press Enter. Legacy form of ``key: Enter``, written as the bare string ``enter``."""

    enter: Literal[True] = True


class CtrlSequence(_Model):
    """Send a control chord such as ``C-c``."""

    ctrl_sequence: str = Field(pattern=r"^C-[A-Za-z@\[\]\\^_]$")


class Hold(_Model):
    """Pause. ``auto`` waits here until the narration has finished.

    Only needed mid-scene: after the last action, a scene always waits for its narration.
    """

    hold: Literal["auto"] | Duration

    @field_validator("hold", mode="before")
    @classmethod
    def _auto_or_ms(cls, value: Any) -> Any:
        if value == "auto":
            return value
        ms = to_ms(value)
        if isinstance(ms, int) and not isinstance(ms, bool) and ms > 0:
            return ms
        raise ValueError(f"expected 'auto' or a positive duration (1500, 1.5s), got {value!r}")


class WaitSpec(_Model):
    """Wait until the screen matches a regular expression, or until the prompt is back."""

    screen: str | None = Field(None, min_length=1, description="Regular expression to wait for.")
    prompt: bool = Field(False, description="Wait until the command has finished and the prompt is back.")
    timeout_ms: Duration = Field(15000, gt=0)

    @field_validator("screen")
    @classmethod
    def _compiles(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            re.compile(value)
        except re.error as error:
            raise ValueError(f"not a valid regular expression: {error}") from error
        return value

    @model_validator(mode="after")
    def _one_condition(self) -> WaitSpec:
        if (self.screen is None) == (not self.prompt):
            raise ValueError("set either screen or prompt: true")
        return self


class Wait(_Model):
    """Block until ``wait.screen`` matches the terminal content, or the prompt is back.

    ``wait: "pattern"`` is short for ``wait: {screen: "pattern"}``.
    """

    wait: WaitSpec

    @field_validator("wait", mode="before")
    @classmethod
    def _pattern_shorthand(cls, value: Any) -> Any:
        return {"screen": value} if isinstance(value, str) else value


class Key(_Model):
    """Press a key, optionally repeated (``Down 3``). Names are case-insensitive."""

    key: str

    @field_validator("key")
    @classmethod
    def _known_key(cls, value: str) -> str:
        if not _KEY_PATTERN.match(value):
            raise ValueError(f"unknown key {value!r}; expected one of {', '.join(VHS_KEYS)}")
        name, _, count = value.partition(" ")
        return f"{_KEY_NAMES[name.lower()]} {count}" if count else _KEY_NAMES[name.lower()]


class Focus(_Model):
    """Move the keyboard to a pane of the editor layout."""

    focus: Literal["explorer", "terminal"]


class Reveal(_Model):
    """Select a file or directory in the editor layout's explorer."""

    reveal: str = Field(min_length=1, description="Path relative to the workspace.")


_Path = Annotated[str, StringConstraints(min_length=1)]
_Paths = Annotated[list[_Path], Field(min_length=1)]


class Diff(_Model):
    """Show what changed in the workspace since the recording started.

    Written as the bare string ``diff`` in YAML, or with paths to limit it to.
    """

    diff: Literal[True] | _Path | _Paths = True

    @property
    def paths(self) -> list[str]:
        """The paths the diff is limited to (empty: everything)."""
        if self.diff is True:
            return []
        return [self.diff] if isinstance(self.diff, str) else list(self.diff)


OverlayPosition = Literal[
    "top-left", "top", "top-right", "left", "center", "right", "bottom-left", "bottom", "bottom-right"
]
_COLOR = r"^#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$"


class OverlayStyle(_Model):
    """How an overlay looks and how long it stays. Unset keys come from its style."""

    position: OverlayPosition | None = Field(None, description="Where in the picture (default bottom-right).")
    size: Literal["small", "medium", "large"] | Annotated[float, Field(gt=0)] | None = Field(
        None,
        description="Text size: small, medium, large, or a factor of terminal.font_size (default medium).",
    )
    color: str | None = Field(None, pattern=_COLOR, description="Text colour, #rrggbb (default #ffffff).")
    background: str | None = Field(
        None, pattern=_COLOR, description="Box colour, #rrggbb or #rrggbbaa with alpha (default #000000b3)."
    )
    box: bool | None = Field(None, description="Draw the rounded box; false shows outlined text only.")
    bold: bool | None = None
    duration_ms: Annotated[Duration, Field(gt=0)] | None = Field(
        None, description="Hide after this long; by default it stays until the scene ends."
    )
    keep: bool | None = Field(
        None, description="Stay past the scene's end until another overlay takes its position."
    )


class Overlay(OverlayStyle):
    """Text shown over the video. ``overlay: "text"`` is short for ``overlay: {text: "text"}``."""

    text: str = Field(min_length=1)
    style: str = Field("default", description="Named style from overlay_styles (built in: default, chapter).")


def _or_text(schema: dict[str, Any]) -> None:
    """Let the schema accept the text shorthand next to the mapping."""
    schema["anyOf"] = [
        {"type": "string", "minLength": 1, "description": "The text; short for {text: ...}."},
        {"$ref": schema.pop("$ref")},
    ]


class ShowOverlay(_Model):
    """Show text over the video from this point (a chapter title, a file name)."""

    overlay: Overlay = Field(json_schema_extra=_or_text)

    @field_validator("overlay", mode="before")
    @classmethod
    def _text_shorthand(cls, value: Any) -> Any:
        return {"text": value} if isinstance(value, str) else value


class Browser(_Model):
    """A web page or local HTML file. ``browser: URL`` is short for ``browser: {url: URL}``."""

    url: str = Field(min_length=1, description="An http(s) URL, or an HTML file in the workspace.")
    scroll: Literal["none", "auto"] | NonNegativeInt = Field(
        "none",
        description="Scroll down while shown: auto (to the end of the page, at most 4 screens) "
        "or this many pixels.",
    )
    duration_ms: Annotated[Duration, Field(gt=0)] | None = Field(
        None, description="Hide after this long; by default it stays until the scene ends."
    )
    load_ms: Annotated[Duration, Field(gt=0)] = Field(
        5000, description="How long the page may load before it is captured."
    )


def _or_url(schema: dict[str, Any]) -> None:
    """Let the schema accept the URL shorthand next to the mapping."""
    schema["anyOf"] = [
        {"type": "string", "minLength": 1, "description": "The URL or file; short for {url: ...}."},
        {"$ref": schema.pop("$ref")},
    ]


class ShowBrowser(_Model):
    """Show a web page over the terminal from this point, as Chromium renders it."""

    browser: Browser = Field(json_schema_extra=_or_url)

    @field_validator("browser", mode="before")
    @classmethod
    def _url_shorthand(cls, value: Any) -> Any:
        return {"url": value} if isinstance(value, str) else value


ACTION_KEYS = (
    "run",
    "type_command",
    "enter",
    "ctrl_sequence",
    "hold",
    "wait",
    "key",
    "focus",
    "reveal",
    "diff",
    "overlay",
    "browser",
)
BARE_ACTIONS = ("enter", "diff")
EDITOR_ACTIONS = ("focus", "reveal")


def _action_tag(value: Any) -> str | None:
    if isinstance(value, BaseModel):
        return next(k for k in ACTION_KEYS if k in type(value).model_fields)
    if isinstance(value, str):
        return value if value in BARE_ACTIONS else None
    if isinstance(value, dict):
        keys = [key for key in value if key in ACTION_KEYS]
        return keys[0] if len(keys) == 1 else None  # other keys are the action's options
    return None


def _expand_shorthand(value: Any) -> Any:
    return {value: True} if isinstance(value, str) and value in BARE_ACTIONS else value


Action = Annotated[
    Annotated[Run, Tag("run")]
    | Annotated[TypeCommand, Tag("type_command")]
    | Annotated[Enter, Tag("enter")]
    | Annotated[CtrlSequence, Tag("ctrl_sequence")]
    | Annotated[Hold, Tag("hold")]
    | Annotated[Wait, Tag("wait")]
    | Annotated[Key, Tag("key")]
    | Annotated[Focus, Tag("focus")]
    | Annotated[Reveal, Tag("reveal")]
    | Annotated[Diff, Tag("diff")]
    | Annotated[ShowOverlay, Tag("overlay")]
    | Annotated[ShowBrowser, Tag("browser")],
    Discriminator(
        _action_tag,
        custom_error_type="invalid_action",
        custom_error_message=(
            "expected 'enter', 'diff' or a mapping with exactly one of: " + ", ".join(ACTION_KEYS)
        ),
    ),
]


class Scene(_Model):
    """One narrated (or silent) step of the video."""

    id: str = Field(pattern=SCENE_ID_PATTERN)
    narration: str | None = None
    actions: list[Action] = []
    hidden: bool = False
    typing_speed_ms: Annotated[Duration, Field(gt=0)] | None = None
    pause_ms: Annotated[Duration, Field(ge=0)] | None = Field(
        None,
        description="Pause after each `key` and `ctrl_sequence` in this scene; defaults to timing.pause_ms.",
    )
    narration_start: Literal["with_actions", "after_actions"] = "with_actions"
    timelapse: float | None = Field(
        None,
        gt=1,
        le=1000,
        description="Show the scene this many times faster (e.g. a long download).",
    )
    expect_exit: ExpectExit | None = Field(
        None,
        description="Exit codes of the scene's commands: success (all exit 0, the default), "
        "failure (at least one fails) or any (not checked).",
    )
    fast: bool | None = Field(
        None,
        description="Fill long pauses with still frames (true) or record them in full (false); "
        "overrides --fast.",
    )

    @field_validator("actions", mode="before")
    @classmethod
    def _shorthand(cls, value: Any) -> Any:
        return [_expand_shorthand(item) for item in value] if isinstance(value, list) else value

    @field_validator("narration")
    @classmethod
    def _normalize_narration(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = " ".join(value.split())
        return text or None

    @model_validator(mode="after")
    def _consistent(self) -> Scene:
        if self.hidden and self.narration:
            raise ValueError("a hidden scene cannot have narration")
        auto_holds = sum(1 for a in self.actions if isinstance(a, Hold) and a.hold == "auto")
        if auto_holds > 1:
            raise ValueError("only one 'hold: auto' is allowed per scene")
        if auto_holds and not self.narration:
            raise ValueError("'hold: auto' needs narration to take its length from")
        if self.timelapse is not None:
            if self.hidden:
                raise ValueError("a hidden scene cannot have a timelapse")
            if auto_holds:
                raise ValueError("a timelapse scene cannot use 'hold: auto'; narration is waited for anyway")
        if self.hidden and any(isinstance(a, ShowOverlay) for a in self.actions):
            raise ValueError("a hidden scene cannot show an overlay")
        if self.hidden and any(isinstance(a, ShowBrowser) for a in self.actions):
            raise ValueError("a hidden scene cannot show a browser")
        return self


# ── top-level sections ────────────────────────────────────────────────────────


class Meta(_Model):
    title: str = "Untitled"


class PiperOptions(_Model):
    length_scale: float = Field(1.0, gt=0)
    sentence_silence: float = Field(0.2, ge=0)


class KokoroOptions(_Model):
    speed: float = Field(1.0, gt=0)
    lang: str | None = Field(None, description="Language code; defaults to the voice's language.")


DEFAULT_VOICES = {"kokoro": "af_heart", "piper": "en_US-lessac-medium"}


class TtsConfig(_Model):
    provider: str = "kokoro"
    voice: str = Field(
        "af_heart",
        description="Voice id; defaults to af_heart for kokoro and en_US-lessac-medium for piper.",
    )
    piper: PiperOptions = PiperOptions()
    kokoro: KokoroOptions = KokoroOptions()
    lexicon: dict[Annotated[str, Field(min_length=1)], Annotated[str, Field(min_length=1)]] = Field(
        {},
        description=(
            "How to say terms the narration spells literally, e.g. {'k8s': 'kubernetes'}. "
            "Overrides the built-in, user and project lexicons."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _provider_default_voice(cls, data: Any) -> Any:
        if isinstance(data, dict) and "voice" not in data:
            provider = data.get("provider", "kokoro")
            if provider in DEFAULT_VOICES:
                return {**data, "voice": DEFAULT_VOICES[provider]}
        return data

    def provider_options(self) -> dict[str, Any]:
        """Options of the selected provider, as a plain dict (part of the cache key).

        The lexicon is not an option: it changes the spoken text, which is in the key.
        """
        options = getattr(self, self.provider, None)
        return options.model_dump() if isinstance(options, BaseModel) else {}


class Timing(_Model):
    narration_buffer_ms: Duration = Field(500, ge=0)
    lead_in_ms: Duration = Field(300, ge=0)
    tail_ms: Duration = Field(1000, ge=0)
    run_hold_ms: Duration = Field(500, ge=0, description="Pause after each `run` action.")
    pause_ms: Duration = Field(100, ge=0, description="Pause after each `key` and `ctrl_sequence`.")


class Terminal(_Model):
    width: int = Field(1200, ge=100)
    height: int = Field(700, ge=100)
    theme: str = "Dracula"
    font_size: int = Field(22, ge=6)
    typing_speed_ms: Duration = Field(40, gt=0)
    shell: Literal["bash", "zsh", "fish", "sh"] = "bash"
    prompt: str = "$ "
    layout: Literal["plain", "editor"] = Field(
        "plain", description="`editor`: a file explorer with preview on top, the shell below (tmux + yazi)."
    )


class Requires(_Model):
    tools: list[str] = []


class Workspace(_Model):
    source: str = "."
    mode: Literal["snapshot", "rw", "ro"] = "snapshot"
    include_uncommitted: bool = True
    caches: dict[str, str] = {}
    artifacts: list[str] = []


class Mount(_Model):
    host: str
    container: str
    mode: Literal["ro", "rw"] = "ro"


class Sandbox(_Model):
    network: Literal["none", "allowlist", "full"] = "none"
    allow_hosts: list[Annotated[str, Field(pattern=HOST_PORT_PATTERN)]] = []
    env_passthrough: list[Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]] = []
    env: dict[str, str] = {}
    extra_mounts: list[Mount] = []
    ssh_agent: bool = False
    docker: bool = Field(
        False,
        description="Give the demo your Docker or Podman engine. This is full control of the host.",
    )

    @model_validator(mode="after")
    def _hosts_need_allowlist(self) -> Sandbox:
        if self.allow_hosts and self.network != "allowlist":
            raise ValueError("allow_hosts only applies with 'network: allowlist'")
        if self.network == "allowlist" and not self.allow_hosts:
            raise ValueError("'network: allowlist' needs at least one entry in allow_hosts")
        return self

    @property
    def elevated(self) -> bool:
        """True when the sandbox asks for more than the locked-down default."""
        return bool(
            self.network != "none"
            or self.env_passthrough
            or self.extra_mounts
            or self.ssh_agent
            or self.docker
        )


ENV_SOURCES = ("image", "compose", "container")
PACKAGE_MANAGERS = ("apt", "apk", "dnf", "microdnf", "yum", "zypper")
PACKAGE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9.+_:=~<>*-]*$"


class EnvCompose(_Model):
    """A service of the project's Compose file (path relative to the spec)."""

    file: str | list[str] = Field("compose.yaml", description="Compose file, or several merged in order.")
    service: str = Field(min_length=1, description="Service the demo shell runs in.")


class Environment(_Model):
    """A project container the demo shell runs in; the rest of narratty stays outside it."""

    image: str | None = Field(None, min_length=1, description="Image to run the demo shell in.")
    compose: EnvCompose | None = Field(None, description="Run in a service of a Compose file.")
    container: str | None = Field(None, min_length=1, description="Run in this running container.")
    workdir: str | None = Field(
        None,
        pattern=r"^/",
        description="Where the shell starts; for image also where the workspace is mounted "
        "(default /work). compose and container default to the container's working directory.",
    )
    user: str = Field(
        "host",
        pattern=r"^(host|image|[0-9]+(:[0-9]+)?|[a-z_][a-z0-9_-]*)$",
        description="host: your user id, so files stay yours; image: the image's user; a user name; "
        "or UID[:GID].",
    )
    env: dict[str, str] = Field({}, description="Variables set in the environment's container.")
    read_only: bool = Field(False, description="Mount the image's root filesystem read-only.")
    packages: list[Annotated[str, Field(pattern=PACKAGE_PATTERN)]] = Field(
        [], description="Packages to add for the demo, with the image's package manager."
    )
    package_manager: Literal["auto", "apt", "apk", "dnf", "microdnf", "yum", "zypper"] = Field(
        "auto", description="auto detects it in the image."
    )
    setup: list[Annotated[str, Field(min_length=1)]] = Field(
        [], description="Shell commands run as root when the image is built (after packages)."
    )
    toolkit: Literal["prefer", "fallback", "off"] = Field(
        "prefer",
        description="Mount narratty's demo toolkit: first on PATH (prefer), last (fallback) or not (off).",
    )

    @model_validator(mode="after")
    def _one_source(self) -> Environment:
        given = [name for name in ENV_SOURCES if getattr(self, name) is not None]
        if len(given) != 1:
            raise ValueError(f"set exactly one of: {', '.join(ENV_SOURCES)}")
        if self.container is not None and self.layered:
            raise ValueError("packages and setup cannot be added to a running container")
        if self.container is not None and self.env:
            raise ValueError("env cannot be set for a running container")
        return self

    @property
    def mount_point(self) -> str:
        """Where image environments mount the workspace."""
        return self.workdir or "/work"

    @property
    def layered(self) -> bool:
        """True when narratty adds packages or setup commands on top of the image."""
        return bool(self.packages or self.setup)

    @property
    def source(self) -> str:
        """The key naming where the container comes from (``image``, …)."""
        return next(name for name in ENV_SOURCES if getattr(self, name) is not None)


class EndCard(_Model):
    """The closing "Created with narratty" card with a link and QR code to the docs."""

    enabled: bool | None = Field(
        None, description="Show the card. Unset follows ~/.config/narratty/config.toml (on by default)."
    )
    duration_ms: Duration = Field(4000, ge=1000, description="How long the card stays on screen.")
    qr: bool = Field(True, description="Show a QR code of the docs link when the terminal is large enough.")


class Spec(_Model):
    """A complete ``.narratty.yaml`` document."""

    version: Literal[1] = 1
    meta: Meta = Meta()
    tts: TtsConfig = TtsConfig()
    timing: Timing = Timing()
    terminal: Terminal = Terminal()
    requires: Requires = Requires()
    workspace: Workspace = Workspace()
    sandbox: Sandbox = Sandbox()
    environment: Environment | None = None
    end_card: EndCard = EndCard()
    subtitles: Literal["none", "files", "track", "burn"] = Field(
        "none",
        description="Subtitles from the narration: files (.srt/.vtt beside the output), "
        "track (soft track in the mp4) or burn (drawn into the video).",
    )
    overlay_styles: dict[Annotated[str, Field(pattern=SCENE_ID_PATTERN)], OverlayStyle] = Field(
        {},
        description="Named overlay styles, used as `overlay: {text: ..., style: <name>}`. "
        "`default` and `chapter` are built in and can be changed here.",
    )
    scenes: list[Scene] = Field(min_length=1)

    @field_validator("end_card", mode="before")
    @classmethod
    def _end_card_shorthand(cls, value: Any) -> Any:
        """``end_card: false`` is short for ``end_card: {enabled: false}``."""
        return {"enabled": value} if isinstance(value, bool) else value

    @model_validator(mode="after")
    def _container_runs_in_place(self) -> Spec:
        if self.environment is not None and self.environment.container and self.workspace.mode != "rw":
            raise ValueError(
                "environment.container runs in the container's own files; set workspace.mode to rw"
            )
        return self

    @model_validator(mode="after")
    def _unique_scene_ids(self) -> Spec:
        seen: set[str] = set()
        for scene in self.scenes:
            if scene.id in seen:
                raise ValueError(f"duplicate scene id {scene.id!r}")
            seen.add(scene.id)
        return self

    @model_validator(mode="after")
    def _known_overlay_styles(self) -> Spec:
        known = {"default", "chapter", *self.overlay_styles}
        for scene in self.scenes:
            for action in scene.actions:
                if isinstance(action, ShowOverlay) and action.overlay.style not in known:
                    raise ValueError(
                        f"scene {scene.id!r}: unknown overlay style {action.overlay.style!r}; "
                        f"expected one of {', '.join(sorted(known))}"
                    )
        return self

    @model_validator(mode="after")
    def _editor_actions_need_the_layout(self) -> Spec:
        if self.terminal.layout == "editor":
            return self
        for scene in self.scenes:
            for action in scene.actions:
                name = next(iter(type(action).model_fields))
                if name in EDITOR_ACTIONS:
                    raise ValueError(f"scene {scene.id!r}: '{name}' needs 'terminal.layout: editor'")
        return self

    @property
    def uses_diff(self) -> bool:
        """True when a scene shows a diff (the recording then starts with a baseline)."""
        return any(isinstance(action, Diff) for scene in self.scenes for action in scene.actions)

    @property
    def narrated_scenes(self) -> list[Scene]:
        """Scenes that have narration, in order."""
        return [scene for scene in self.scenes if scene.narration]
