/**
 * F17 W.1 — barrel export for the icon library.
 *
 * Consumers should import from `@/components/icons` (this barrel)
 * instead of the per-file paths. Keeps the public surface stable
 * when files get reorganized.
 */

export { CommanderCrown } from "./Commander";
export {
  EliteSpecIcon,
  ProfessionIcon,
  getEliteIconPath,
  getProfessionIconPath,
} from "./Professions";
