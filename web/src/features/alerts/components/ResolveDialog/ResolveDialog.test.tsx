import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ResolveDialog } from "./ResolveDialog";

const defaultProps = {
  open: true,
  onClose: jest.fn(),
  onSubmit: jest.fn().mockResolvedValue(undefined),
};

describe("ResolveDialog", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("is hidden when open is false", () => {
    render(<ResolveDialog {...defaultProps} open={false} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("is visible when open is true", () => {
    render(<ResolveDialog {...defaultProps} />);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("shows error for resolutionType after blur when empty", async () => {
    render(<ResolveDialog {...defaultProps} />);
    const select = screen.getByRole("combobox");
    fireEvent.blur(select);
    await waitFor(() =>
      expect(
        screen.getByText(/resolution type is required/i)
      ).toBeInTheDocument()
    );
  });

  it("shows error for rootCause after blur when empty", async () => {
    render(<ResolveDialog {...defaultProps} />);
    const rootCauseInput = screen.getByLabelText(/root cause/i);
    fireEvent.blur(rootCauseInput);
    await waitFor(() =>
      expect(screen.getByText(/root cause is required/i)).toBeInTheDocument()
    );
  });

  it("shows error for actionTaken after blur when empty", async () => {
    render(<ResolveDialog {...defaultProps} />);
    const actionInput = screen.getByLabelText(/action taken/i);
    fireEvent.blur(actionInput);
    await waitFor(() =>
      expect(screen.getByText(/action taken is required/i)).toBeInTheDocument()
    );
  });

  it("does not show error for preventiveMeasures when empty", async () => {
    render(<ResolveDialog {...defaultProps} />);
    const pmInput = screen.getByLabelText(/preventive measures/i);
    fireEvent.blur(pmInput);
    await waitFor(() =>
      expect(
        screen.queryByText(/preventive measures.*required/i)
      ).not.toBeInTheDocument()
    );
  });

  it("submit button is disabled when form is invalid", () => {
    render(<ResolveDialog {...defaultProps} />);
    const btn = screen.getByRole("button", { name: /resolve/i });
    expect(btn).toBeDisabled();
  });

  it("submit button is enabled when all required fields are valid", async () => {
    const user = userEvent.setup();
    render(<ResolveDialog {...defaultProps} />);

    fireEvent.mouseDown(screen.getByLabelText(/resolution type/i));
    await waitFor(() => screen.getByRole("listbox"));
    fireEvent.click(screen.getByRole("option", { name: "Repaired" }));

    await user.type(screen.getByLabelText(/root cause/i), "Cause");
    await user.type(screen.getByLabelText(/action taken/i), "Action");

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /resolve/i })).not.toBeDisabled()
    );
  });

  it("shows API error inside dialog and stays open on 409", async () => {
    const onSubmit = jest.fn().mockRejectedValue({
      status: 409,
      data: { detail: "Alert is already resolved." },
    });
    const user = userEvent.setup();
    render(<ResolveDialog {...defaultProps} onSubmit={onSubmit} />);

    fireEvent.mouseDown(screen.getByLabelText(/resolution type/i));
    await waitFor(() => screen.getByRole("listbox"));
    fireEvent.click(screen.getByRole("option", { name: "Repaired" }));
    await user.type(screen.getByLabelText(/root cause/i), "Cause");
    await user.type(screen.getByLabelText(/action taken/i), "Action");

    fireEvent.click(screen.getByRole("button", { name: /resolve/i }));

    await waitFor(() =>
      expect(
        screen.getByText(/Alert is already resolved/i)
      ).toBeInTheDocument()
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("closes on successful submit", async () => {
    const onClose = jest.fn();
    const onSubmit = jest.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <ResolveDialog {...defaultProps} onClose={onClose} onSubmit={onSubmit} />
    );

    fireEvent.mouseDown(screen.getByLabelText(/resolution type/i));
    await waitFor(() => screen.getByRole("listbox"));
    fireEvent.click(screen.getByRole("option", { name: "Repaired" }));
    await user.type(screen.getByLabelText(/root cause/i), "Cause");
    await user.type(screen.getByLabelText(/action taken/i), "Action");

    fireEvent.click(screen.getByRole("button", { name: /resolve/i }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});
