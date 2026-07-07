/**
 * AG Grid Community 33+ ships in tree-shaken mode and requires an
 * explicit module registration. Each grid component in this app
 * imports this file -- the side effect runs once at module load
 * (TypeScript/Next.js guarantees a single evaluation of the module
 * graph), so ``ModuleRegistry.registerModules`` fires exactly once
 * no matter which grid component the user lands on first.
 *
 * Without this, a user who navigates directly to a fight-detail
 * page (and never visits ``/fights``) would see an unstyled grid
 * with broken sorting + filter because the AllCommunityModule
 * wouldn't have been registered. Centralising the registration
 * here removes that ordering hazard.
 *
 * NOTE: keep this file SIDE-EFFECT ONLY. No exported symbols --
 * any consumer that needs an AG Grid type should import from
 * ``ag-grid-community`` directly so the import is type-only and
 * tree-shakable.
 */
import { AllCommunityModule, ModuleRegistry } from "ag-grid-community";

ModuleRegistry.registerModules([AllCommunityModule]);
