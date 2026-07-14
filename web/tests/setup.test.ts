import { describe, expect, it, vi } from "vitest";

import { dispatchStorageEvent } from "./setup";

describe("dispatchStorageEvent helper", () => {
  it("dispatches a storage event that a window listener receives", () => {
    const listener = vi.fn();
    window.addEventListener("storage", listener);
    try {
      dispatchStorageEvent("gw2analytics:timeline-scale", "log", "linear");
      expect(listener).toHaveBeenCalledTimes(1);
      const event = listener.mock.calls[0][0] as StorageEvent;
      expect(event.key).toBe("gw2analytics:timeline-scale");
      expect(event.newValue).toBe("log");
      expect(event.oldValue).toBe("linear");
      // The mock store is updated to reflect the cross-tab observable state.
      expect(window.localStorage.getItem("gw2analytics:timeline-scale")).toBe("log");
    } finally {
      window.removeEventListener("storage", listener);
    }
  });
});
