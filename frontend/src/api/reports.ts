import { apiClient } from './client';
import {
  DumpingReport,
  DumpingReportCreatePayload,
  ReportEvidence,
} from '../types';

export interface WardSummary {
  id: string;
  name: string;
  ward_number: string;
}

/**
 * Submits a new illegal dumping incident report to the backend.
 * Requires authenticated citizen session.
 */
export async function createDumpingReport(
  payload: DumpingReportCreatePayload
): Promise<DumpingReport> {
  return apiClient.post<DumpingReport>('/reports', payload);
}

/**
 * Uploads an individual photographic evidence file for a created report.
 * Requires that the authenticated citizen is the original reporter.
 * Supports JPEG, PNG, and WebP up to 5MB.
 */
export async function uploadReportEvidence(
  reportId: string,
  file: File
): Promise<ReportEvidence> {
  const formData = new FormData();
  formData.append('file', file, file.name);
  return apiClient.postForm<ReportEvidence>(`/reports/${reportId}/evidence`, formData);
}

/**
 * Fetches all incident reports submitted by the currently authenticated citizen.
 */
export async function getMyReports(): Promise<DumpingReport[]> {
  return apiClient.get<DumpingReport[]>('/reports/me');
}

/**
 * Fetches available administrative wards for optional incident ward tagging.
 * Public and unauthenticated.
 */
export async function fetchWardsForSelection(): Promise<WardSummary[]> {
  return apiClient.get<WardSummary[]>('/wards');
}


/**
 * Fetches reports for official review (Supervisors and Municipal Admins).
 */
export async function fetchReportsForReview(options: {
  wardId?: string;
  status?: string;
} = {}): Promise<DumpingReport[]> {
  const params = new URLSearchParams();
  if (options.wardId) params.set('ward_id', options.wardId);
  if (options.status) params.set('status', options.status);
  const query = params.toString() ? `?${params.toString()}` : '';
  return apiClient.get<DumpingReport[]>(`/reports${query}`);
}

/**
 * Updates report lifecycle status with official review notes.
 */
export async function updateReportStatus(
  reportId: string,
  payload: {
    status: 'UNDER_REVIEW' | 'ACTION_SCHEDULED' | 'RESOLVED' | 'REJECTED';
    official_notes?: string;
  }
): Promise<DumpingReport> {
  return apiClient.request<DumpingReport>(`/reports/${reportId}/status`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
    headers: { 'Content-Type': 'application/json' },
  });
}
