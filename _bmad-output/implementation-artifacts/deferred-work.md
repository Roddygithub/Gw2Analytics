# Travail différé

Findings identifiés en review mais hors périmètre de la story, collectés pour une attention focalisée ultérieure.

- source_spec: `_bmad-output/specs/spec-ei-parity-certification/stories/2-normaliser-le-rapport-de-certification.md`
  summary: Régénérer la baseline `corpus-baseline.json` en octets identiques sur le corpus privé complet avant de certifier le format.
  evidence: La baseline octet-pour-octet ne peut être vérifiée sans les logs/EVTC privés absents du worktree ; le reviewer a confirmé que `--json` story 1 doit rester inchangé.
- source_spec: `_bmad-output/specs/spec-ei-parity-certification/stories/2-normaliser-le-rapport-de-certification.md`
  summary: Ajouter un test du chemin `OSError` et du message de rename lors de l'écriture atomique du rapport.
  evidence: Le chemin d'erreur de l'écriture atomique (échec `os.replace`) n'est pas couvert ; préexistant à la story, surfaces par le nouveau rapport schema v1.