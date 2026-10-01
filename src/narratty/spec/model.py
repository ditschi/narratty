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
    Tag,
    WithJsonSchema,
    field_validator,
    model_validator,
)

SCENE_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]*$"
HOST_PORT_PATTERN = r"^[A-Za-z0-9.-]+:[0-9]{1,5}$"

# Special keys VHS understands (optionally followed by a repeat count, e.g. "Down 3").
VHS_KEYS = (
    "Backspace",
    "Delete",
    "Down",
    "End",
    "Enter",
    "Escape",
    "Home",
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


class Run(_Model):
    """Type a command, press Enter, then pause for ``timing.run_hold_ms``."""

    run: str = Field(min_length=1)


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
    """Wait until the screen matches a regular expression."""

    screen: str = Field(min_length=1)
    timeout_ms: Duration = Field(15000, gt=0)

    @field_validator("screen")
    @classmethod
    def _compiles(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as error:
            raise ValueError(f"not a valid regular expression: {error}") from error
        return value


class Wait(_Model):
    """Block until ``wait.screen`` matches the terminal content.

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


ACTION_KEYS = ("run", "type_command", "enter", "ctrl_sequence", "hold", "wait", "key")


def _action_tag(value: Any) -> str | None:
    if isinstance(value, BaseModel):
        return next(k for k in ACTION_KEYS if k in type(value).model_fields)
    if isinstance(value, str):
        return value if value == "enter" else None
    if isinstance(value, dict) and len(value) == 1:
        key = next(iter(value))
        return key if key in ACTION_KEYS else None
    return None


def _expand_shorthand(value: Any) -> Any:
    return {"enter": True} if value == "enter" else value


Action = Annotated[
    Annotated[Run, Tag("run")]
    | Annotated[TypeCommand, Tag("type_command")]
    | Annotated[Enter, Tag("enter")]
    | Annotated[CtrlSequence, Tag("ctrl_sequence")]
    | Annotated[Hold, Tag("hold")]
    | Annotated[Wait, Tag("wait")]
    | Annotated[Key, Tag("key")],
    Discriminator(
        _action_tag,
        custom_error_type="invalid_action",
        custom_error_message=("expected 'enter' or a mapping with exactly one of: " + ", ".join(ACTION_KEYS)),
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
        return bool(self.network != "none" or self.env_passthrough or self.extra_mounts or self.ssh_agent)


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
    end_card: EndCard = EndCard()
    subtitles: Literal["none", "files", "track", "burn"] = Field(
        "none",
        description="Subtitles from the narration: files (.srt/.vtt beside the output), "
        "track (soft track in the mp4) or burn (drawn into the video).",
    )
    scenes: list[Scene] = Field(min_length=1)

    @field_validator("end_card", mode="before")
    @classmethod
    def _end_card_shorthand(cls, value: Any) -> Any:
        """``end_card: false`` is short for ``end_card: {enabled: false}``."""
        return {"enabled": value} if isinstance(value, bool) else value

    @model_validator(mode="after")
    def _unique_scene_ids(self) -> Spec:
        seen: set[str] = set()
        for scene in self.scenes:
            if scene.id in seen:
                raise ValueError(f"duplicate scene id {scene.id!r}")
            seen.add(scene.id)
        return self

    @property
    def narrated_scenes(self) -> list[Scene]:
        """Scenes that have narration, in order."""
        return [scene for scene in self.scenes if scene.narration]
