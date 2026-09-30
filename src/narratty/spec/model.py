"""Pydantic models for ``.narratty.yaml``.

Every model forbids unknown keys, so typos surface as validation errors instead
of being silently ignored.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    PositiveInt,
    Tag,
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
_KEY_PATTERN = re.compile(rf"^({'|'.join(VHS_KEYS)})( [1-9][0-9]*)?$")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ── actions ───────────────────────────────────────────────────────────────────


class TypeCommand(_Model):
    """Type text at the scene's typing speed (does not press Enter)."""

    type_command: str = Field(min_length=1)


class Enter(_Model):
    """Press Enter. Written as the bare string ``enter`` in YAML."""

    enter: Literal[True] = True


class CtrlSequence(_Model):
    """Send a control chord such as ``C-c``."""

    ctrl_sequence: str = Field(pattern=r"^C-[A-Za-z@\[\]\\^_]$")


class Hold(_Model):
    """Pause. ``auto`` fills the scene until its narration has finished."""

    hold: Literal["auto"] | PositiveInt

    @field_validator("hold", mode="before")
    @classmethod
    def _auto_or_ms(cls, value: Any) -> Any:
        if value == "auto" or (isinstance(value, int) and not isinstance(value, bool) and value > 0):
            return value
        raise ValueError(f"expected 'auto' or a positive number of milliseconds, got {value!r}")


class WaitSpec(_Model):
    """Wait until the screen matches a regular expression."""

    screen: str = Field(min_length=1)
    timeout_ms: PositiveInt = 15000

    @field_validator("screen")
    @classmethod
    def _compiles(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as error:
            raise ValueError(f"not a valid regular expression: {error}") from error
        return value


class Wait(_Model):
    """Block until ``wait.screen`` matches the terminal content."""

    wait: WaitSpec


class Key(_Model):
    """Press a raw VHS key, optionally repeated (``Down 3``)."""

    key: str

    @field_validator("key")
    @classmethod
    def _known_key(cls, value: str) -> str:
        if not _KEY_PATTERN.match(value):
            raise ValueError(f"unknown key {value!r}; expected one of {', '.join(VHS_KEYS)}")
        return value


ACTION_KEYS = ("type_command", "enter", "ctrl_sequence", "hold", "wait", "key")


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
    Annotated[TypeCommand, Tag("type_command")]
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
    typing_speed_ms: PositiveInt | None = None
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
    narration_buffer_ms: int = Field(500, ge=0)
    lead_in_ms: int = Field(300, ge=0)
    tail_ms: int = Field(1000, ge=0)


class Terminal(_Model):
    width: int = Field(1200, ge=100)
    height: int = Field(700, ge=100)
    theme: str = "Dracula"
    font_size: int = Field(22, ge=6)
    typing_speed_ms: PositiveInt = 40
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


ENV_SOURCES = ("image",)


class Environment(_Model):
    """A project container the demo shell runs in; the rest of narratty stays outside it."""

    image: str | None = Field(None, min_length=1, description="Image to run the demo shell in.")
    workdir: str = Field(
        "/work", pattern=r"^/", description="Where the workspace is mounted and the shell starts."
    )
    user: str = Field(
        "host",
        pattern=r"^(host|image|[0-9]+(:[0-9]+)?)$",
        description="host: your user id, so files stay yours; image: the image's user; or UID[:GID].",
    )
    read_only: bool = Field(False, description="Mount the image's root filesystem read-only.")

    @model_validator(mode="after")
    def _one_source(self) -> Environment:
        given = [name for name in ENV_SOURCES if getattr(self, name) is not None]
        if len(given) != 1:
            raise ValueError(f"set exactly one of: {', '.join(ENV_SOURCES)}")
        return self

    @property
    def source(self) -> str:
        """The key naming where the container comes from (``image``, …)."""
        return next(name for name in ENV_SOURCES if getattr(self, name) is not None)


class EndCard(_Model):
    """The closing "Created with narratty" card with a link and QR code to the docs."""

    enabled: bool | None = Field(
        None, description="Show the card. Unset follows ~/.config/narratty/config.toml (on by default)."
    )
    duration_ms: int = Field(4000, ge=1000, description="How long the card stays on screen.")
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
