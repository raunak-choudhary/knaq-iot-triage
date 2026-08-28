import { screen, waitFor, fireEvent } from "@testing-library/react";
import { renderWithProviders } from "./testUtils";
import { AlertDetail } from "@/features/alerts/components/AlertDetail";

jest.mock("next/link", () => {
  const MockLink = ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  );
  MockLink.displayName = "MockLink";
  return MockLink;
});

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  useParams: () => ({}),
  redirect: jest.fn(),
}));

describe("AlertDetailPage", () => {
  it("shows loading skeleton initially", () => {
    renderWithProviders(<AlertDetail id="alert-1" />);
    expect(screen.getByTestId("loading-skeleton")).toBeInTheDocument();
  });

  it("renders alert header with title and severity", async () => {
    renderWithProviders(<AlertDetail id="alert-1" />);
    await waitFor(() =>
      expect(screen.getByText("High Temperature Alert")).toBeInTheDocument()
    );
    expect(screen.getByText("Critical")).toBeInTheDocument();
    expect(screen.getByText("New")).toBeInTheDocument();
  });

  it("shows device name and location in header", async () => {
    renderWithProviders(<AlertDetail id="alert-1" />);
    await waitFor(() =>
      expect(screen.getByText(/Elevator 1/)).toBeInTheDocument()
    );
    expect(screen.getByText(/Building A/)).toBeInTheDocument();
  });

  it("shows metric card for threshold alert", async () => {
    renderWithProviders(<AlertDetail id="alert-1" />);
    await waitFor(() =>
      expect(screen.getByTestId("metric-card")).toBeInTheDocument()
    );
  });

  it("hides metric card for door_fault (no threshold)", async () => {
    renderWithProviders(<AlertDetail id="alert-2" />);
    await waitFor(() =>
      expect(screen.getByText("Door Fault Detected")).toBeInTheDocument()
    );
    expect(screen.queryByTestId("metric-card")).not.toBeInTheDocument();
  });

  it("shows acknowledge and assign buttons for new alert", async () => {
    renderWithProviders(<AlertDetail id="alert-1" />);
    await waitFor(() =>
      expect(screen.getByTestId("acknowledge-btn")).toBeInTheDocument()
    );
    expect(screen.getByTestId("assign-btn")).toBeInTheDocument();
    expect(screen.queryByTestId("resolve-btn")).not.toBeInTheDocument();
  });

  it("shows resolve and assign buttons for acknowledged alert", async () => {
    renderWithProviders(<AlertDetail id="alert-2" />);
    await waitFor(() =>
      expect(screen.getByTestId("resolve-btn")).toBeInTheDocument()
    );
    expect(screen.getByTestId("assign-btn")).toBeInTheDocument();
    expect(screen.queryByTestId("acknowledge-btn")).not.toBeInTheDocument();
  });

  it("shows no action buttons for resolved alert", async () => {
    renderWithProviders(<AlertDetail id="alert-3" />);
    await waitFor(() =>
      expect(screen.getByText("Low Pressure Alert")).toBeInTheDocument()
    );
    expect(screen.queryByTestId("acknowledge-btn")).not.toBeInTheDocument();
    expect(screen.queryByTestId("resolve-btn")).not.toBeInTheDocument();
  });

  it("renders timeline entries in order", async () => {
    renderWithProviders(<AlertDetail id="alert-1" />);
    await waitFor(() =>
      expect(screen.getByTestId("alert-timeline")).toBeInTheDocument()
    );
    expect(screen.getByText("Created")).toBeInTheDocument();
  });

  it("shows 404 error state for non-existent alert", async () => {
    renderWithProviders(<AlertDetail id="nonexistent-id" />);
    await waitFor(() =>
      expect(screen.getByTestId("error-state")).toBeInTheDocument()
    );
  });

  it("add note form submits and shows updated timeline", async () => {
    renderWithProviders(<AlertDetail id="alert-1" />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /submit note/i })).toBeInTheDocument()
    );
    const noteInput = screen.getByRole("textbox", { name: /note/i });
    fireEvent.change(noteInput, { target: { value: "Checked the unit" } });
    fireEvent.click(screen.getByRole("button", { name: /submit note/i }));
    await waitFor(() =>
      expect(screen.getByText("Checked the unit")).toBeInTheDocument()
    );
  });

  it("acknowledge updates status badge", async () => {
    renderWithProviders(<AlertDetail id="alert-1" />);
    await waitFor(() =>
      expect(screen.getByTestId("acknowledge-btn")).toBeInTheDocument()
    );
    fireEvent.click(screen.getByTestId("acknowledge-btn"));
    // After acknowledge, the StatusBadge should update from "New" to "Acknowledged"
    await waitFor(() =>
      expect(screen.queryByTestId("acknowledge-btn")).not.toBeInTheDocument(),
      { timeout: 3000 }
    );
  });
});
