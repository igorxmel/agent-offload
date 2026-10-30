"""Privacy policy: what counts as acceptable for this project's code.

The policy describes **selection rules**, not model names. A person says
"no training on my prompts, retention no longer than a week", and a fresh table
from the official page decides which models fit.

The core principle: **unknown is denied.** A model with no data is not allowed
until a person allows it. Otherwise a broken page parser would silently open
access to everything, including models that train on prompts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from offload import jsonio, paths
from offload.privacy import Privacy, normalize

# Ready-made answers to "what kind of code is this". `init` asks the question.
PRESETS: dict[str, dict] = {
    "strict": {
        "allow_training": False,
        "max_retention_days": 0,
        "require_known": True,
        "about": "closed or sensitive code: no training and no retention of prompts",
    },
    "private": {
        "allow_training": False,
        "max_retention_days": 30,
        "require_known": True,
        "about": "ordinary code: no training, retention up to 30 days is acceptable",
    },
    "open": {
        "allow_training": True,
        "max_retention_days": None,
        "require_known": False,
        "about": "open-source code: anything goes, including models that train on prompts",
    },
}

DEFAULT_PRESET = "strict"


@dataclass
class Policy:
    allow_training: bool = False
    max_retention_days: int | None = 0
    require_known: bool = True
    # Manual exceptions. Stored as written, compared in normalised form.
    allowed: list[str] = field(default_factory=list)
    denied: list[str] = field(default_factory=list)

    @classmethod
    def from_preset(cls, name: str) -> Policy:
        preset = PRESETS[name]
        return cls(
            allow_training=preset["allow_training"],
            max_retention_days=preset["max_retention_days"],
            require_known=preset["require_known"],
        )

    def to_dict(self) -> dict:
        return {
            "allow_training": self.allow_training,
            "max_retention_days": self.max_retention_days,
            "require_known": self.require_known,
            "allowed": self.allowed,
            "denied": self.denied,
        }


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason: str


def load(root) -> Policy:
    data = jsonio.read(paths.policy_file(root), None)
    if data is None:
        # No file: the strictest policy applies, not the loosest.
        return Policy.from_preset(DEFAULT_PRESET)
    base = Policy.from_preset(DEFAULT_PRESET)
    return Policy(
        allow_training=bool(data.get("allow_training", base.allow_training)),
        max_retention_days=data.get("max_retention_days", base.max_retention_days),
        require_known=bool(data.get("require_known", base.require_known)),
        allowed=list(data.get("allowed", [])),
        denied=list(data.get("denied", [])),
    )


def save(root, policy: Policy) -> None:
    jsonio.write(paths.policy_file(root), policy.to_dict())


def short_id(model_id: str) -> str:
    """`opencode/beam-free` -> `beam-free`: the table does not name the provider."""
    return model_id.rsplit("/", 1)[-1]


def _listed(model_id: str, names: list[str]) -> bool:
    # `provider/*` covers a whole provider: a free-tier key makes all of its models
    # free for this person, which no catalog can know.
    provider = model_id.split("/", 1)[0]
    if any(name.strip() == f"{provider}/*" for name in names):
        return True
    keys = {normalize(name) for name in names} | {normalize(short_id(n)) for n in names}
    return normalize(short_id(model_id)) in keys or normalize(model_id) in keys


def evaluate(
    model_id: str,
    privacy: Privacy | None,
    policy: Policy,
    *,
    cost: list[float] | None,
    tools: bool | None,
) -> Verdict:
    """Whether a model is acceptable. Checks run in order of importance.

    `cost` is [input, output] dollars per million tokens, or None when unknown;
    `tools` is whether the model can call tools, or None when unknown. Both are
    required arguments on purpose: there is no default that could quietly mean
    "free" or "capable".
    """
    if _listed(model_id, policy.denied):
        return Verdict(False, "denied manually")
    if _listed(model_id, policy.allowed):
        return Verdict(True, "allowed manually")

    # Price before privacy: the kit is for free models, and an unknown price is
    # treated like unknown terms - denied until a person decides.
    if cost is None:
        return Verdict(False, "price unknown (to allow: offload allow <model>)")
    if max(cost) > 0:
        return Verdict(
            False,
            f"paid: ${cost[0]:g} in / ${cost[1]:g} out per 1M tokens "
            "(free-tier key? offload allow <provider>/*)",
        )
    if tools is None:
        return Verdict(False, "unknown whether it can call tools (an agent needs them)")
    if not tools:
        return Verdict(False, "cannot call tools (an agent needs them)")

    if privacy is None:
        if policy.require_known:
            return Verdict(False, "no privacy data (to allow: offload allow <model>)")
        return Verdict(True, "no privacy data, but the policy permits that")

    if privacy.trains is True and not policy.allow_training:
        return Verdict(False, "prompts are used for training")
    if privacy.trains is None and policy.require_known:
        return Verdict(False, "unknown whether prompts are used for training")

    limit = policy.max_retention_days
    if limit is not None:
        if privacy.retention_days is None:
            if policy.require_known:
                return Verdict(False, "prompt retention period unknown")
        elif privacy.retention_days > limit:
            return Verdict(False, f"retention {privacy.retention_days} days, limit {limit}")

    return Verdict(True, "fits the policy")
