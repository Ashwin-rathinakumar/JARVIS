import re
import string
import difflib
from typing import Optional, List, Dict, Any, Set
from dataclasses import dataclass, field

from app.utils.logger import logger

COMMAND_VERB_PATTERNS = [
    r"^(?:open|launch|close|start|run|stop|terminate|kill|inspect|status\s+of|analyze)\b",
]

CONTEXT_PREFIX_PATTERNS = [
    r"^(?:the\s+)?(?:project|workspace|folder|repo|repository)\s+(?:called|named)\s+",
    r"^(?:called|named)\s+",
    r"^(?:the\s+)?project\s+",
    r"^(?:my\s+)?project\s+",
    r"^(?:the\s+)?workspace\s+",
    r"^(?:my\s+)?workspace\s+",
    r"^(?:the\s+)?folder\s+",
    r"^(?:my\s+)?folder\s+",
    r"^(?:the\s+)?repo\s+",
    r"^(?:my\s+)?repo\s+",
    r"^(?:the\s+)?repository\s+",
    r"^(?:my\s+)?repository\s+",
    r"^(?:the\s+)?app\s+",
    r"^(?:the\s+)?application\s+",
    r"^(?:the|a|my)\s+",
]

CONTEXT_SUFFIX_PATTERNS = [
    r"\s+project\s+name$",
    r"\s+(?:the\s+)?project$",
    r"\s+project$",
    r"\s+(?:the\s+)?workspace$",
    r"\s+workspace$",
    r"\s+(?:the\s+)?repo$",
    r"\s+repo$",
    r"\s+(?:the\s+)?repository$",
    r"\s+repository$",
    r"\s+(?:the\s+)?app$",
    r"\s+app$",
    r"\s+(?:the\s+)?folder$",
    r"\s+folder$",
]

GENERIC_PLACEHOLDERS: Set[str] = {
    "",
    "project",
    "project name",
    "the project",
    "a project",
    "my project",
    "new project",
    "a new project",
    "repo",
    "the repo",
    "repository",
    "app",
    "application",
    "folder",
    "workspace",
    "new",
}


def extract_project_candidate(transcript: str) -> Optional[str]:
    """
    Extract clean project candidate string from speech/text transcript.
    Removes command verbs, punctuation, and anchored project-context wrappers.
    Returns None if extraction yields no candidate or a generic placeholder ('project', 'new project').
    """
    if not transcript:
        return None

    s = transcript.strip()
    if not s:
        return None

    s = s.strip("\"'’`")
    s = re.sub(r"^[\s,.:;!?-]+", "", s)
    s = re.sub(r"[\s,.:;!?-]+$", "", s)

    # Clean harmless punctuation immediately following command verb (e.g. "Open, Sentinel AI" -> "Open Sentinel AI")
    s = re.sub(r"^(open|launch|close|start|run|stop|inspect|analyze|status)\s*[,.:;]\s*", r"\1 ", s, flags=re.IGNORECASE)

    lower_s = s.lower().strip()

    # Remove leading command verb (open, launch, start, run, stop, inspect, status of, analyze)
    m_verb = re.match(r"^(open|launch|close|start|run|stop|terminate|kill|inspect|status\s+of|analyze)\s+(.+)$", lower_s, re.IGNORECASE)
    if m_verb:
        candidate_part = s[len(m_verb.group(1)):].strip()
        candidate_part = re.sub(r"^[\s,.:;!?-]+", "", candidate_part)
    else:
        candidate_part = s

    # Remove leading context wrappers (e.g., "the project ", "project ")
    changed = True
    while changed and candidate_part:
        changed = False
        lower_cand = candidate_part.lower().strip()
        for pat in CONTEXT_PREFIX_PATTERNS:
            m = re.match(pat, lower_cand, re.IGNORECASE)
            if m and len(lower_cand) > m.end():
                candidate_part = candidate_part[m.end():].strip()
                changed = True
                break

    # Remove trailing context wrappers (e.g., " project", " project.", " repo.")
    candidate_part = re.sub(r"[\s,.:;!?-]+$", "", candidate_part)

    changed = True
    while changed and candidate_part:
        changed = False
        lower_cand = candidate_part.lower().strip()
        for pat in CONTEXT_SUFFIX_PATTERNS:
            m = re.search(pat, lower_cand, re.IGNORECASE)
            if m:
                candidate_part = candidate_part[:m.start()].strip()
                candidate_part = re.sub(r"[\s,.:;!?-]+$", "", candidate_part)
                changed = True
                break

    candidate_part = candidate_part.strip("\"'’` ,.:;!?")

    if not candidate_part or candidate_part.lower().strip() in GENERIC_PLACEHOLDERS:
        return None

    return candidate_part


def normalize_project_name(name: str, remove_context_prefix: bool = True) -> str:
    """
    Generic project name normalizer.
    Lowercases, strips whitespace/quotes/punctuation, normalizes dots, hyphens, and spaces.
    Optionally strips contextual prefix and suffix words like 'project' or 'repo'.
    """
    if not name:
        return ""

    s = name.strip().lower()
    s = s.strip("\"'’`")
    s = re.sub(r"^[\s,.:;!?-]+", "", s)
    s = re.sub(r"[\s,.:;!?-]+$", "", s)

    if remove_context_prefix:
        extracted = extract_project_candidate(s)
        if extracted:
            s = extracted.lower()

    # Replace hyphens and underscores with spaces
    s = re.sub(r"[-_]+", " ", s)

    # Remove all punctuation except space
    s = s.translate(str.maketrans("", "", string.punctuation))

    # Collapse multiple spaces
    s = re.sub(r"\s+", " ", s).strip()
    return s


@dataclass
class ProjectResolution:
    """Structure representing the result of project name entity resolution."""
    matched: bool
    canonical_name: Optional[str] = None
    project_key: Optional[str] = None
    project: Optional[Dict[str, Any]] = None
    confidence: float = 0.0
    match_type: str = "none"  # "exact_canonical", "exact_normalized", "explicit_alias", "generated_alias", "fuzzy"
    ambiguous: bool = False
    candidates: List[str] = field(default_factory=list)
    message: Optional[str] = None


class ProjectResolver:
    """
    Generic project-name entity resolver.
    Resolves spoken or typed project references to canonical project keys in PROJECTS registry.
    """

    def __init__(self, projects_registry: Optional[Dict[str, Dict[str, Any]]] = None):
        self._registry = projects_registry

    @property
    def projects(self) -> Dict[str, Dict[str, Any]]:
        if self._registry is not None:
            return self._registry
        from app.config.projects import PROJECTS
        return PROJECTS

    def _generate_aliases(self, key: str, proj: Dict[str, Any]) -> Set[str]:
        """
        Derive automatic safe aliases for a registered project.
        Supports acronyms (K.E.E.R., R.A.G.), spaces (Sentinel AI), hyphens, etc.
        """
        aliases: Set[str] = set()
        c_name = proj.get("name", key).strip()

        aliases.add(key.lower())
        aliases.add(c_name.lower())

        norm = normalize_project_name(c_name)
        if norm:
            aliases.add(norm)

        # Acronym & Dot handling (e.g. K.E.E.R. -> keer, k.e.e.r, k e e r, k-e-e-r)
        if "." in c_name:
            no_dots = c_name.replace(".", "").lower().strip()
            if no_dots:
                aliases.add(no_dots)
                aliases.add(" ".join(list(no_dots)))
                aliases.add("-".join(list(no_dots)))

            parts = [p.lower() for p in c_name.split(".") if p.strip()]
            if parts:
                aliases.add(".".join(parts))
                aliases.add(".".join(parts) + ".")

        # Multi-word handling (e.g. Sentinel AI -> sentinel ai, sentinel-ai, sentinelai)
        words = c_name.split()
        if len(words) > 1:
            joined = "".join(w.lower() for w in words if w.strip())
            hyphenated = "-".join(w.lower() for w in words if w.strip())
            aliases.add(joined)
            aliases.add(hyphenated)

            # Significant individual words (>= 4 chars)
            for w in words:
                w_clean = normalize_project_name(w)
                if len(w_clean) >= 4 and w_clean not in {"project", "system", "app", "application"}:
                    aliases.add(w_clean)

        # Multi-word >= 3 words (e.g. Streetlight Fault Reporting System -> streetlight system)
        if len(words) >= 3:
            first_last = f"{words[0]} {words[-1]}".lower()
            aliases.add(first_last)
            aliases.add(normalize_project_name(first_last))

        return aliases

    def resolve(
        self,
        spoken_name: str,
        threshold: float = 0.78,
        margin: float = 0.08,
    ) -> ProjectResolution:
        """
        Resolve a spoken/typed project candidate to a canonical project in the registry.
        Enforces 6-level matching priority and ambiguity margin checks.
        """
        if not spoken_name or not spoken_name.strip():
            return ProjectResolution(matched=False, message="No project name specified.")

        raw_cand = spoken_name.strip()

        # Extract clean candidate if raw utterance contains wrappers/verbs
        extracted_cand = extract_project_candidate(raw_cand)
        cand_for_matching = extracted_cand if extracted_cand else raw_cand

        norm_cand = normalize_project_name(cand_for_matching)
        joined_cand = re.sub(r"\s+", "", norm_cand)

        # Priority 1: Exact Canonical Name Match (Case-insensitive)
        canonical_matches = {}
        for key, proj in self.projects.items():
            c_name = proj.get("name", key).strip()
            if (
                cand_for_matching.lower() == c_name.lower()
                or cand_for_matching.lower() == key.lower()
                or raw_cand.lower() == c_name.lower()
            ):
                canonical_matches[key] = (c_name, proj)

        if len(canonical_matches) == 1:
            key, (c_name, proj) = next(iter(canonical_matches.items()))
            res = ProjectResolution(
                matched=True,
                canonical_name=c_name,
                project_key=key,
                project=proj,
                confidence=1.0,
                match_type="exact_canonical",
                message=f"Resolved '{spoken_name}' to {c_name}.",
            )
            self._log_resolution(spoken_name, cand_for_matching, norm_cand, res)
            return res
        elif len(canonical_matches) > 1:
            cand_names = [proj.get("name", k) for k, (c_name, proj) in canonical_matches.items()]
            msg = f"I found more than one matching project: {' and '.join(cand_names)}. Which one do you want?"
            res = ProjectResolution(
                matched=False,
                ambiguous=True,
                candidates=cand_names,
                confidence=1.0,
                message=msg,
            )
            self._log_resolution(spoken_name, cand_for_matching, norm_cand, res)
            return res

        # Priority 2: Exact Normalized Name Match
        norm_matches = {}
        for key, proj in self.projects.items():
            c_name = proj.get("name", key).strip()
            if norm_cand and (norm_cand == normalize_project_name(c_name) or norm_cand == normalize_project_name(key)):
                norm_matches[key] = (c_name, proj)

        if len(norm_matches) == 1:
            key, (c_name, proj) = next(iter(norm_matches.items()))
            res = ProjectResolution(
                matched=True,
                canonical_name=c_name,
                project_key=key,
                project=proj,
                confidence=1.0,
                match_type="exact_normalized",
                message=f"Resolved '{spoken_name}' to {c_name}.",
            )
            self._log_resolution(spoken_name, cand_for_matching, norm_cand, res)
            return res
        elif len(norm_matches) > 1:
            cand_names = [proj.get("name", k) for k, (c_name, proj) in norm_matches.items()]
            msg = f"I found more than one matching project: {' and '.join(cand_names)}. Which one do you want?"
            res = ProjectResolution(
                matched=False,
                ambiguous=True,
                candidates=cand_names,
                confidence=1.0,
                message=msg,
            )
            self._log_resolution(spoken_name, cand_for_matching, norm_cand, res)
            return res

        # Priority 3: Exact Explicit Alias Match
        explicit_matches = {}
        for key, proj in self.projects.items():
            c_name = proj.get("name", key).strip()
            explicit_aliases = proj.get("aliases", [])
            for alias in explicit_aliases:
                norm_alias = normalize_project_name(alias)
                joined_alias = re.sub(r"\s+", "", norm_alias)
                if (
                    (norm_cand and norm_cand == norm_alias)
                    or (joined_cand and joined_cand == joined_alias)
                    or cand_for_matching.lower() == alias.lower()
                ):
                    explicit_matches[key] = (c_name, proj)
                    break

        if len(explicit_matches) == 1:
            key, (c_name, proj) = next(iter(explicit_matches.items()))
            res = ProjectResolution(
                matched=True,
                canonical_name=c_name,
                project_key=key,
                project=proj,
                confidence=1.0,
                match_type="explicit_alias",
                message=f"Resolved '{spoken_name}' to {c_name}.",
            )
            self._log_resolution(spoken_name, cand_for_matching, norm_cand, res)
            return res
        elif len(explicit_matches) > 1:
            cand_names = [proj.get("name", k) for k, (c_name, proj) in explicit_matches.items()]
            msg = f"I found more than one matching project: {' and '.join(cand_names)}. Which one do you want?"
            res = ProjectResolution(
                matched=False,
                ambiguous=True,
                candidates=cand_names,
                confidence=1.0,
                message=msg,
            )
            self._log_resolution(spoken_name, cand_for_matching, norm_cand, res)
            return res

        # Priority 4: Exact Generated Alias Match
        gen_matches = {}
        for key, proj in self.projects.items():
            c_name = proj.get("name", key).strip()
            gen_aliases = self._generate_aliases(key, proj)
            for alias in gen_aliases:
                norm_alias = normalize_project_name(alias)
                joined_alias = re.sub(r"\s+", "", norm_alias)
                if (
                    (norm_cand and norm_cand == norm_alias)
                    or (joined_cand and joined_cand == joined_alias)
                    or cand_for_matching.lower() == alias.lower()
                ):
                    gen_matches[key] = (c_name, proj)
                    break

        if len(gen_matches) == 1:
            key, (c_name, proj) = next(iter(gen_matches.items()))
            res = ProjectResolution(
                matched=True,
                canonical_name=c_name,
                project_key=key,
                project=proj,
                confidence=0.95,
                match_type="generated_alias",
                message=f"Resolved '{spoken_name}' to {c_name}.",
            )
            self._log_resolution(spoken_name, cand_for_matching, norm_cand, res)
            return res
        elif len(gen_matches) > 1:
            cand_names = [proj.get("name", k) for k, (c_name, proj) in gen_matches.items()]
            msg = f"I found more than one matching project: {' and '.join(cand_names)}. Which one do you want?"
            res = ProjectResolution(
                matched=False,
                ambiguous=True,
                candidates=cand_names,
                confidence=0.95,
                message=msg,
            )
            self._log_resolution(spoken_name, cand_for_matching, norm_cand, res)
            return res

        # Priority 5: Conservative Fuzzy Match
        project_scores: Dict[str, float] = {}
        for key, proj in self.projects.items():
            c_name = proj.get("name", key).strip()
            all_aliases: Set[str] = set()
            all_aliases.add(c_name.lower())
            all_aliases.add(key.lower())
            all_aliases.add(normalize_project_name(c_name))

            for a in proj.get("aliases", []):
                all_aliases.add(a.lower())
                all_aliases.add(normalize_project_name(a))

            for a in self._generate_aliases(key, proj):
                all_aliases.add(a.lower())
                all_aliases.add(normalize_project_name(a))

            best_p_score = 0.0
            for alias in all_aliases:
                if not alias:
                    continue
                ratio = difflib.SequenceMatcher(None, norm_cand, alias).ratio()
                ratio_joined = difflib.SequenceMatcher(None, joined_cand, re.sub(r"\s+", "", alias)).ratio()
                max_r = max(ratio, ratio_joined)
                if max_r > best_p_score:
                    best_p_score = max_r

            project_scores[key] = best_p_score

        sorted_projs = sorted(project_scores.items(), key=lambda x: x[1], reverse=True)

        if not sorted_projs:
            res = ProjectResolution(matched=False, message=f"I don't know the project '{spoken_name}'.")
            self._log_resolution(spoken_name, cand_for_matching, norm_cand, res)
            return res

        top_key, top_score = sorted_projs[0]
        second_key, second_score = sorted_projs[1] if len(sorted_projs) > 1 else (None, 0.0)

        if top_score < threshold:
            res = ProjectResolution(
                matched=False,
                confidence=top_score,
                message=f"I don't know the project '{spoken_name}'.",
            )
            self._log_resolution(spoken_name, cand_for_matching, norm_cand, res)
            return res

        # Priority 6: Ambiguity Check
        if second_key and second_score >= threshold and (top_score - second_score) < margin:
            cand_keys = [k for k, s in sorted_projs if s >= threshold and (top_score - s) < margin]
            cand_names = [self.projects[k].get("name", k) for k in cand_keys]
            msg = f"I found more than one matching project: {' and '.join(cand_names)}. Which one do you want?"
            res = ProjectResolution(
                matched=False,
                ambiguous=True,
                candidates=cand_names,
                confidence=top_score,
                message=msg,
            )
            self._log_resolution(spoken_name, cand_for_matching, norm_cand, res)
            return res

        top_proj = self.projects[top_key]
        c_name = top_proj.get("name", top_key).strip()
        res = ProjectResolution(
            matched=True,
            canonical_name=c_name,
            project_key=top_key,
            project=top_proj,
            confidence=top_score,
            match_type="fuzzy",
            message=f"Resolved '{spoken_name}' to {c_name}.",
        )
        self._log_resolution(spoken_name, cand_for_matching, norm_cand, res)
        return res

    def _log_resolution(self, raw: str, cand: str, norm: str, res: ProjectResolution) -> None:
        """Structured trace logging for project resolution."""
        logger.debug(
            "Project resolution raw=%r candidate=%r normalized_candidate=%r canonical=%r match_type=%s score=%.2f",
            raw, cand, norm, res.canonical_name, res.match_type, res.confidence,
        )


# Global singleton resolver instance
project_resolver = ProjectResolver()
