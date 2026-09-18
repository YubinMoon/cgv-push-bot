import { describe, expect, it, vi } from "vitest";
import { fireEvent, render } from "@testing-library/react";
import { Modal } from "./components";

describe("Modal", () => {
  it("closes the topmost dialog with Escape", () => {
    const onClose = vi.fn();
    render(
      <Modal title="상세" onClose={onClose}>
        <button>확인</button>
      </Modal>,
    );

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).toHaveBeenCalledOnce();
  });
});
