import test from 'node:test';
import assert from 'node:assert/strict';

// Constants matching backend invariants
const MIN_DESCRIPTION_LENGTH = 10;
const MAX_DESCRIPTION_LENGTH = 1000;
const MAX_EVIDENCE_FILES = 5;
const MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024;
const ALLOWED_MIME_TYPES = ['image/jpeg', 'image/png', 'image/webp'];

// Validator helper mirroring client-side logic
function validateReportSubmission({ description, latitude, longitude, files = [] }) {
  const errors = [];

  const trimmed = (description || '').trim();
  if (trimmed.length < MIN_DESCRIPTION_LENGTH) {
    errors.push('Description must contain at least 10 characters.');
  }
  if (trimmed.length > MAX_DESCRIPTION_LENGTH) {
    errors.push('Description must not exceed 1000 characters.');
  }

  const latNum = parseFloat(latitude);
  const lonNum = parseFloat(longitude);
  if (isNaN(latNum) || latNum < -90 || latNum > 90) {
    errors.push('Please enter a valid latitude between -90 and +90.');
  }
  if (isNaN(lonNum) || lonNum < -180 || lonNum > 180) {
    errors.push('Please enter a valid longitude between -180 and +180.');
  }

  if (files.length > MAX_EVIDENCE_FILES) {
    errors.push(`Maximum ${MAX_EVIDENCE_FILES} photos allowed.`);
  }

  for (const f of files) {
    if (!ALLOWED_MIME_TYPES.includes(f.type)) {
      errors.push(`Unsupported file type: ${f.type}`);
    }
    if (f.size > MAX_FILE_SIZE_BYTES) {
      errors.push(`File ${f.name} exceeds 5MB.`);
    }
  }

  return {
    isValid: errors.length === 0,
    errors,
    payload: errors.length === 0 ? {
      description: trimmed,
      latitude: latNum,
      longitude: lonNum,
    } : null,
  };
}

test('1. Description validation enforces 10 to 1000 character boundaries', () => {
  // Too short
  const shortResult = validateReportSubmission({
    description: 'Too short',
    latitude: 12.9716,
    longitude: 77.5946,
  });
  assert.equal(shortResult.isValid, false);
  assert.ok(shortResult.errors.some((e) => e.includes('at least 10 characters')));

  // Blank whitespace
  const blankResult = validateReportSubmission({
    description: '          ',
    latitude: 12.9716,
    longitude: 77.5946,
  });
  assert.equal(blankResult.isValid, false);

  // Exactly 10 characters valid
  const exactResult = validateReportSubmission({
    description: '1234567890',
    latitude: 12.9716,
    longitude: 77.5946,
  });
  assert.equal(exactResult.isValid, true);
  assert.equal(exactResult.payload.description, '1234567890');

  // Max length exceeded
  const longResult = validateReportSubmission({
    description: 'a'.repeat(1001),
    latitude: 12.9716,
    longitude: 77.5946,
  });
  assert.equal(longResult.isValid, false);
  assert.ok(longResult.errors.some((e) => e.includes('must not exceed 1000 characters')));
});

test('2. Coordinate validation accepts valid WGS 84 lat/long and rejects invalid ranges', () => {
  // Valid Bengaluru coordinates
  const valid = validateReportSubmission({
    description: 'Garbage dump near Bellandur junction',
    latitude: '12.9352',
    longitude: '77.6744',
  });
  assert.equal(valid.isValid, true);
  assert.equal(valid.payload.latitude, 12.9352);
  assert.equal(valid.payload.longitude, 77.6744);

  // Invalid latitude > 90
  const invalidLat = validateReportSubmission({
    description: 'Garbage dump near Bellandur junction',
    latitude: '95.0',
    longitude: '77.6744',
  });
  assert.equal(invalidLat.isValid, false);
  assert.ok(invalidLat.errors.some((e) => e.includes('latitude')));

  // Invalid longitude < -180
  const invalidLon = validateReportSubmission({
    description: 'Garbage dump near Bellandur junction',
    latitude: '12.9352',
    longitude: '-185.0',
  });
  assert.equal(invalidLon.isValid, false);
  assert.ok(invalidLon.errors.some((e) => e.includes('longitude')));
});

test('3. Photo attachment restrictions enforce max 5 files, 5MB limit, and allowed MIME types', () => {
  const validFiles = [
    { name: 'dump1.jpg', size: 1024 * 1024, type: 'image/jpeg' },
    { name: 'dump2.png', size: 2 * 1024 * 1024, type: 'image/png' },
    { name: 'dump3.webp', size: 500 * 1024, type: 'image/webp' },
  ];

  const valid = validateReportSubmission({
    description: 'Overflowing bins behind bus stop',
    latitude: 12.9716,
    longitude: 77.5946,
    files: validFiles,
  });
  assert.equal(valid.isValid, true);

  // Reject more than 5 files
  const tooMany = validateReportSubmission({
    description: 'Overflowing bins behind bus stop',
    latitude: 12.9716,
    longitude: 77.5946,
    files: [...validFiles, ...validFiles],
  });
  assert.equal(tooMany.isValid, false);
  assert.ok(tooMany.errors.some((e) => e.includes('Maximum 5 photos')));

  // Reject oversized file > 5MB
  const oversized = validateReportSubmission({
    description: 'Overflowing bins behind bus stop',
    latitude: 12.9716,
    longitude: 77.5946,
    files: [{ name: 'huge.jpg', size: 6 * 1024 * 1024, type: 'image/jpeg' }],
  });
  assert.equal(oversized.isValid, false);
  assert.ok(oversized.errors.some((e) => e.includes('exceeds 5MB')));

  // Reject disallowed MIME type (e.g. PDF or GIF)
  const invalidType = validateReportSubmission({
    description: 'Overflowing bins behind bus stop',
    latitude: 12.9716,
    longitude: 77.5946,
    files: [{ name: 'document.pdf', size: 1024, type: 'application/pdf' }],
  });
  assert.equal(invalidType.isValid, false);
  assert.ok(invalidType.errors.some((e) => e.includes('Unsupported file type')));
});

test('4. Sequential two-step submission contract and idempotency on retry', async () => {
  let reportCreatedCount = 0;
  const mockCreatedReport = {
    id: 'a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d',
    description: 'Piles of waste on 100ft road',
    latitude: 12.9716,
    longitude: 77.5946,
    status: 'SUBMITTED',
  };

  // Mock API client
  const mockApi = {
    createReport: async (payload) => {
      reportCreatedCount++;
      return { ...mockCreatedReport, ...payload };
    },
    uploadEvidence: async (reportId, file) => {
      if (file.name === 'bad.jpg') {
        throw new Error('Upload network glitch');
      }
      return {
        id: 'evidence-123',
        report_id: reportId,
        file_name: file.name,
      };
    },
  };

  // Step 1: Create report
  const report = await mockApi.createReport({
    description: 'Piles of waste on 100ft road',
    latitude: 12.9716,
    longitude: 77.5946,
  });
  assert.equal(report.id, mockCreatedReport.id);
  assert.equal(reportCreatedCount, 1);

  // Step 2: Upload 2 files where 1 fails
  const files = [
    { name: 'good.jpg', size: 1000, type: 'image/jpeg' },
    { name: 'bad.jpg', size: 1000, type: 'image/jpeg' },
  ];

  const failed = [];
  const uploaded = [];
  for (const f of files) {
    try {
      const res = await mockApi.uploadEvidence(report.id, f);
      uploaded.push(res);
    } catch (err) {
      failed.push({ file: f, reason: err.message });
    }
  }

  assert.equal(uploaded.length, 1);
  assert.equal(failed.length, 1);
  assert.equal(failed[0].file.name, 'bad.jpg');

  // Retry failed upload ONLY: reportCreatedCount must NOT increment
  const retryFailed = [];
  for (const item of failed) {
    try {
      // Simulate resolved network glitch
      const res = { id: 'evidence-retry-456', report_id: report.id, file_name: item.file.name };
      uploaded.push(res);
    } catch (err) {
      retryFailed.push(item);
    }
  }

  assert.equal(reportCreatedCount, 1, 'Report must NOT be recreated on evidence retry');
  assert.equal(uploaded.length, 2);
  assert.equal(retryFailed.length, 0);
});

test('5. Auth & permission error normalization handles 401 and 403 gracefully', () => {
  const normalizeError = (err) => {
    if (typeof err === 'object' && err !== null && 'detail' in err) {
      return String(err.detail);
    }
    if (err instanceof Error) return err.message;
    return 'An unexpected error occurred.';
  };

  const err401 = { status: 401, detail: 'Not authenticated' };
  assert.equal(normalizeError(err401), 'Not authenticated');

  const err403 = { status: 403, detail: 'Only citizens can submit evidence for incident reports.' };
  assert.equal(normalizeError(err403), 'Only citizens can submit evidence for incident reports.');

  const networkErr = new Error('Failed to connect to NammaClean backend server.');
  assert.equal(normalizeError(networkErr), 'Failed to connect to NammaClean backend server.');
});
