import { createApi, fetchBaseQuery } from "@reduxjs/toolkit/query/react";
import type {
  AlertResponse,
  AlertStats,
  BulkOperationResult,
  Device,
  PaginatedAlertsResponse,
  Reading,
  User,
} from "@/features/alerts/types";

export interface GetAlertsParams {
  severity?: string[];
  status?: string[];
  device_id?: string;
  assigned_to?: string;
  q?: string;
  from?: string;
  to?: string;
  page?: number;
  page_size?: number;
}

export interface AssignBody {
  assignee_id: string;
  note?: string;
}

export interface ResolveBody {
  resolution_type: string;
  root_cause: string;
  action_taken: string;
  preventive_measures?: string;
  time_spent_minutes?: number;
}

export interface AddNoteBody {
  note: string;
}

export interface DismissBody {
  note?: string;
}

export interface BulkAcknowledgeBody {
  alert_ids: string[];
}

export interface BulkAssignBody {
  alert_ids: string[];
  assignee_id: string;
  note?: string;
}

export const alertsApi = createApi({
  reducerPath: "alertsApi",
  baseQuery: fetchBaseQuery({
    baseUrl: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
    prepareHeaders: (headers) => {
      const token = process.env.NEXT_PUBLIC_AUTH_TOKEN;
      if (token) {
        headers.set("Authorization", `Bearer ${token}`);
      }
      return headers;
    },
  }),
  tagTypes: ["Alert", "Device", "User"],
  endpoints: (builder) => ({
    getAlerts: builder.query<PaginatedAlertsResponse, GetAlertsParams>({
      query: (params) => {
        const searchParams = new URLSearchParams();
        if (params.severity) {
          params.severity.forEach((s) => searchParams.append("severity", s));
        }
        if (params.status) {
          params.status.forEach((s) => searchParams.append("status", s));
        }
        if (params.device_id) searchParams.set("device_id", params.device_id);
        if (params.assigned_to)
          searchParams.set("assigned_to", params.assigned_to);
        if (params.q) searchParams.set("q", params.q);
        if (params.from) searchParams.set("from", params.from);
        if (params.to) searchParams.set("to", params.to);
        if (params.page) searchParams.set("page", String(params.page));
        if (params.page_size) searchParams.set("page_size", String(params.page_size));
        return `/alerts?${searchParams.toString()}`;
      },
      providesTags: [{ type: "Alert", id: "LIST" }],
    }),
    getAlertStats: builder.query<AlertStats, void>({
      query: () => "/alerts/stats",
      providesTags: [{ type: "Alert", id: "STATS" }],
    }),
    getAlertById: builder.query<AlertResponse, string>({
      query: (id) => `/alerts/${id}`,
      providesTags: (_result, _error, id) => [{ type: "Alert", id }],
    }),
    getDevices: builder.query<Device[], void>({
      query: () => "/devices",
      providesTags: [{ type: "Device", id: "LIST" }],
    }),
    getDevice: builder.query<Device, string>({
      query: (id) => `/devices/${id}`,
      providesTags: (_result, _error, id) => [{ type: "Device", id }],
    }),
    getDeviceReadings: builder.query<
      Reading[],
      { id: string; start?: string; end?: string }
    >({
      query: ({ id, start, end }) => {
        const params = new URLSearchParams();
        if (start) params.set("start", start);
        if (end) params.set("end", end);
        return `/devices/${id}/readings?${params.toString()}`;
      },
    }),
    getUsers: builder.query<User[], void>({
      query: () => "/users",
      providesTags: [{ type: "User", id: "LIST" }],
    }),
    acknowledge: builder.mutation<AlertResponse, string>({
      query: (id) => ({
        url: `/alerts/${id}/acknowledge`,
        method: "POST",
      }),
      // Bonus 3: Optimistic UI — immediately update status in detail cache, roll back on rejection
      async onQueryStarted(id, { dispatch, queryFulfilled }) {
        const patch = dispatch(
          alertsApi.util.updateQueryData("getAlertById", id, (draft) => {
            draft.status = "acknowledged";
          })
        );
        try {
          await queryFulfilled;
        } catch {
          patch.undo();
        }
      },
      invalidatesTags: (_result, _error, id) => [
        { type: "Alert", id },
        { type: "Alert", id: "LIST" },
        { type: "Alert", id: "STATS" },
      ],
    }),
    assign: builder.mutation<AlertResponse, { id: string; body: AssignBody }>({
      query: ({ id, body }) => ({
        url: `/alerts/${id}/assign`,
        method: "POST",
        body,
      }),
      invalidatesTags: (_result, _error, { id }) => [
        { type: "Alert", id },
        { type: "Alert", id: "LIST" },
        { type: "Alert", id: "STATS" },
      ],
    }),
    resolve: builder.mutation<AlertResponse, { id: string; body: ResolveBody }>(
      {
        query: ({ id, body }) => ({
          url: `/alerts/${id}/resolve`,
          method: "POST",
          body,
        }),
        invalidatesTags: (_result, _error, { id }) => [
          { type: "Alert", id },
          { type: "Alert", id: "LIST" },
          { type: "Alert", id: "STATS" },
        ],
      }
    ),
    addNote: builder.mutation<AlertResponse, { id: string; body: AddNoteBody }>(
      {
        query: ({ id, body }) => ({
          url: `/alerts/${id}/notes`,
          method: "POST",
          body,
        }),
        invalidatesTags: (_result, _error, { id }) => [
          { type: "Alert", id },
          { type: "Alert", id: "LIST" },
        ],
      }
    ),
    dismiss: builder.mutation<AlertResponse, { id: string; body: DismissBody }>(
      {
        query: ({ id, body }) => ({
          url: `/alerts/${id}/dismiss`,
          method: "POST",
          body,
        }),
        invalidatesTags: (_result, _error, { id }) => [
          { type: "Alert", id },
          { type: "Alert", id: "LIST" },
          { type: "Alert", id: "STATS" },
        ],
      }
    ),
    reopen: builder.mutation<AlertResponse, string>({
      query: (id) => ({
        url: `/alerts/${id}/reopen`,
        method: "POST",
      }),
      invalidatesTags: (_result, _error, id) => [
        { type: "Alert", id },
        { type: "Alert", id: "LIST" },
        { type: "Alert", id: "STATS" },
      ],
    }),
    bulkAcknowledge: builder.mutation<BulkOperationResult, BulkAcknowledgeBody>({
      query: (body) => ({
        url: "/alerts/bulk/acknowledge",
        method: "POST",
        body,
      }),
      invalidatesTags: [
        { type: "Alert", id: "LIST" },
        { type: "Alert", id: "STATS" },
      ],
    }),
    bulkAssign: builder.mutation<BulkOperationResult, BulkAssignBody>({
      query: (body) => ({
        url: "/alerts/bulk/assign",
        method: "POST",
        body,
      }),
      invalidatesTags: [
        { type: "Alert", id: "LIST" },
        { type: "Alert", id: "STATS" },
      ],
    }),
  }),
});

export const {
  useGetAlertsQuery,
  useGetAlertByIdQuery,
  useGetAlertStatsQuery,
  useGetDevicesQuery,
  useGetDeviceQuery,
  useGetDeviceReadingsQuery,
  useGetUsersQuery,
  useAcknowledgeMutation,
  useAssignMutation,
  useResolveMutation,
  useAddNoteMutation,
  useDismissMutation,
  useReopenMutation,
  useBulkAcknowledgeMutation,
  useBulkAssignMutation,
} = alertsApi;
