"use client";

import { useState, useMemo, useCallback, useEffect, useRef } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Pagination from "@mui/material/Pagination";
import Typography from "@mui/material/Typography";
import TextField from "@mui/material/TextField";
import Select from "@mui/material/Select";
import MenuItem from "@mui/material/MenuItem";
import FormControl from "@mui/material/FormControl";
import InputLabel from "@mui/material/InputLabel";
import OutlinedInput from "@mui/material/OutlinedInput";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import type { SelectChangeEvent } from "@mui/material/Select";
import { useAppDispatch, useAppSelector } from "@/lib/store";
import {
  setSeverity,
  setStatus,
  setDeviceId,
  setSearchQuery,
  setSortBy,
  setSortDir,
  clearFilters,
} from "@/features/alerts/slices/filtersSlice";
import {
  useGetAlertsQuery,
  useGetDevicesQuery,
  useGetUsersQuery,
  useAcknowledgeMutation,
  useAssignMutation,
  useBulkAcknowledgeMutation,
} from "@/features/alerts/api/alertsApi";
import { AssignDialog } from "@/features/alerts/components/AssignDialog";
import { SummaryBar } from "@/features/alerts/components/SummaryBar";
import { AlertTable } from "@/features/alerts/components/AlertTable";
import { LoadingSkeleton } from "@/components/ui/LoadingSkeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { useToast } from "@/components/ui/AppToast";
import type { AlertStatus, Severity } from "@/features/alerts/types";
import { extractApiError } from "@/utils/errorHelpers";
import { SEVERITY_LABEL } from "@/constants/severity";

const SEVERITIES: Severity[] = ["critical", "warning", "info"];

function useDebounce(value: string, delay: number): string {
  const [debouncedValue, setDebouncedValue] = useState(value);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setDebouncedValue(value), delay);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [value, delay]);

  return debouncedValue;
}

export default function AlertsPage() {
  const dispatch = useAppDispatch();
  const filters = useAppSelector((s) => s.filters);
  const { showToast } = useToast();
  const [localSearch, setLocalSearch] = useState("");

  const debouncedSearch = useDebounce(localSearch, 400);

  const [assignAlertId, setAssignAlertId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 10;

  // Reset to page 1 when any filter or search changes. Adjusting during render
  // instead of in an effect avoids a second commit with a stale page number.
  const filterKey = JSON.stringify([
    filters.severity,
    filters.status,
    filters.deviceId,
    debouncedSearch,
  ]);
  const [prevFilterKey, setPrevFilterKey] = useState(filterKey);
  if (filterKey !== prevFilterKey) {
    setPrevFilterKey(filterKey);
    setPage(1);
  }

  const queryParams = useMemo(
    () => ({
      severity: filters.severity.length ? filters.severity : undefined,
      status: filters.status.length ? filters.status : undefined,
      device_id: filters.deviceId ?? undefined,
      q: debouncedSearch || undefined,
      page,
      page_size: PAGE_SIZE,
    }),
    [filters.severity, filters.status, filters.deviceId, debouncedSearch, page]
  );

  const { data: alertsData, isLoading, isError, refetch } = useGetAlertsQuery(queryParams);
  // Stable reference: `alerts` is a dependency of the keyboard shortcut effect,
  // so a fresh array each render would re-bind the listener on every render.
  const alerts = useMemo(() => alertsData?.items ?? [], [alertsData]);
  const totalPages = alertsData?.total_pages ?? 1;
  const statusCounts = alertsData?.status_counts ?? { new: 0, acknowledged: 0, resolved: 0, dismissed: 0 };
  const { data: devicesData } = useGetDevicesQuery();
  const devices = devicesData ?? [];
  const { data: usersData = [] } = useGetUsersQuery();
  const [acknowledge] = useAcknowledgeMutation();
  const [assign] = useAssignMutation();
  const [bulkAcknowledge] = useBulkAcknowledgeMutation();

  const handleAcknowledge = useCallback(
    async (id: string) => {
      try {
        await acknowledge(id).unwrap();
        showToast("Alert acknowledged", "success");
      } catch (err) {
        showToast(extractApiError(err), "error");
      }
    },
    [acknowledge, showToast]
  );

  const handleBulkAcknowledge = useCallback(
    async (ids: string[]) => {
      if (ids.length === 0) return;
      try {
        const result = await bulkAcknowledge({ alert_ids: ids }).unwrap();
        setSelectedIds(new Set());
        if (result.failed > 0) {
          showToast(`${result.succeeded} acknowledged, ${result.failed} failed`, "warning");
        } else {
          showToast(`${result.succeeded} alert${result.succeeded !== 1 ? "s" : ""} acknowledged`, "success");
        }
      } catch {
        showToast("Bulk acknowledge failed", "error");
      }
    },
    [bulkAcknowledge, showToast]
  );

  // Keyboard shortcuts — 'A' to acknowledge selected new alerts
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement).tagName.toLowerCase();
      if (tag === "input" || tag === "textarea" || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key.toLowerCase() === "a") {
        const newIds = [...selectedIds].filter(
          (id) => alerts.find((a) => a.id === id)?.status === "new"
        );
        if (newIds.length > 0) handleBulkAcknowledge(newIds);
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [selectedIds, alerts, handleBulkAcknowledge]);

  // Selection helpers
  function toggleSelect(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    if (selectedIds.size === alerts.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(alerts.map((a) => a.id)));
    }
  }

  function handleSeverityChange(e: SelectChangeEvent<string[]>) {
    const value = e.target.value;
    dispatch(setSeverity(typeof value === "string" ? value.split(",") : value));
  }

  function handleDeviceChange(e: SelectChangeEvent<string>) {
    dispatch(setDeviceId(e.target.value || null));
  }

  function handleStatusClick(status: AlertStatus) {
    const newStatus = filters.status.includes(status)
      ? filters.status.filter((s) => s !== status)
      : [...filters.status, status];
    dispatch(setStatus(newStatus));
  }

  const handleAssignFromQueue = useCallback(
    async (body: { assignee_id: string; note?: string }) => {
      if (!assignAlertId) return;
      try {
        await assign({ id: assignAlertId, body }).unwrap();
        showToast("Alert assigned", "success");
        setAssignAlertId(null);
      } catch (err) {
        showToast(extractApiError(err), "error");
        throw err;
      }
    },
    [assign, assignAlertId, showToast]
  );

  function handleSortChange(key: "severity" | "time" | "status") {
    if (filters.sortBy === key) {
      dispatch(setSortDir(filters.sortDir === "asc" ? "desc" : "asc"));
    } else {
      dispatch(setSortBy(key));
      dispatch(setSortDir("desc"));
    }
  }

  return (
    <Box sx={{ p: { xs: 1, sm: 2, md: 3 } }}>
      <Box sx={{ mb: 2, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <Typography variant="h5" sx={{ fontWeight: 700 }}>
          Alert Queue
        </Typography>
        <Button
          variant="contained"
          color="error"
          size="small"
          onClick={() => {
            dispatch(clearFilters());
            setLocalSearch("");
          }}
        >
          Clear filters
        </Button>
      </Box>

      {!isLoading && (
        <SummaryBar
          statusCounts={statusCounts}
          selectedStatus={filters.status}
          onStatusClick={handleStatusClick}
        />
      )}

      <Stack
        direction={{ xs: "column", sm: "row" }}
        spacing={1}
        sx={{ my: 2, flexWrap: "wrap" }}
      >
        <TextField
          size="small"
          label="Search alerts"
          value={localSearch}
          onChange={(e) => {
            setLocalSearch(e.target.value);
            dispatch(setSearchQuery(e.target.value));
          }}
          sx={{ minWidth: 200 }}
        />

        <FormControl size="small" sx={{ minWidth: 160 }}>
          <InputLabel id="severity-label">Severity</InputLabel>
          <Select
            labelId="severity-label"
            multiple
            value={filters.severity}
            onChange={handleSeverityChange}
            input={<OutlinedInput label="Severity" />}
            renderValue={(selected) =>
              (selected as string[]).map((s) => SEVERITY_LABEL[s as Severity]).join(", ")
            }
          >
            {SEVERITIES.map((s) => (
              <MenuItem key={s} value={s}>
                {SEVERITY_LABEL[s]}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        <FormControl size="small" sx={{ minWidth: 160 }}>
          <InputLabel id="device-label">Device</InputLabel>
          <Select
            labelId="device-label"
            value={filters.deviceId ?? ""}
            onChange={handleDeviceChange}
            label="Device"
          >
            <MenuItem value="">All Devices</MenuItem>
            {devices.map((d) => (
              <MenuItem key={d.device_id} value={d.device_id}>
                {d.name}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      </Stack>

      {filters.severity.length > 0 && (
        <Box sx={{ display: "flex", gap: 0.5, flexWrap: "wrap", mb: 1 }}>
          {filters.severity.map((s) => (
            <Chip
              key={s}
              label={SEVERITY_LABEL[s as Severity]}
              size="small"
              onDelete={() =>
                dispatch(setSeverity(filters.severity.filter((v) => v !== s)))
              }
            />
          ))}
        </Box>
      )}

      {isLoading && <LoadingSkeleton rows={8} />}
      {isError && (
        <ErrorState
          message="Failed to load alerts."
          onRetry={() => refetch()}
        />
      )}
      {!isLoading && !isError && alerts.length === 0 && <EmptyState />}
      {!isLoading && !isError && alerts.length > 0 && (
        <>
          <AlertTable
            alerts={alerts}
            sortBy={filters.sortBy}
            sortDir={filters.sortDir}
            onSortChange={handleSortChange}
            onAcknowledge={handleAcknowledge}
            onAssign={(id) => setAssignAlertId(id)}
            selectedIds={selectedIds}
            onToggleSelect={toggleSelect}
            onToggleAll={toggleAll}
            onBulkAcknowledge={handleBulkAcknowledge}
          />
          {totalPages > 1 && (
            <Box sx={{ display: "flex", justifyContent: "center", mt: 2 }}>
              <Pagination
                count={totalPages}
                page={page}
                onChange={(_e, value) => setPage(value)}
                color="primary"
                shape="rounded"
              />
            </Box>
          )}
        </>
      )}

      <AssignDialog
        open={!!assignAlertId}
        onClose={() => setAssignAlertId(null)}
        onSubmit={handleAssignFromQueue}
        users={usersData}
        currentAssigneeId={
          assignAlertId
            ? (alerts.find((a) => a.id === assignAlertId)?.assigned_to ?? null)
            : null
        }
      />
    </Box>
  );
}
