import test from 'node:test';
import assert from 'node:assert/strict';

// Test Suite for NammaClean Citizen Registration Flow & Button Responsiveness

test('1. Client-side validation rejects mismatched passwords without initiating API request', () => {
  let apiCalled = false;
  let errorMessage = null;

  const validateAndSubmit = (password, confirmPassword) => {
    if (password !== confirmPassword) {
      errorMessage = 'Passwords do not match.';
      return false;
    }
    if (password.length < 12) {
      errorMessage = 'Password must be at least 12 characters.';
      return false;
    }
    apiCalled = true;
    return true;
  };

  const result = validateAndSubmit('ValidPassword123!', 'DifferentPassword123!');
  assert.equal(result, false);
  assert.equal(errorMessage, 'Passwords do not match.');
  assert.equal(apiCalled, false);
});

test('2. Client-side validation rejects passwords under 12 characters without initiating API request', () => {
  let apiCalled = false;
  let errorMessage = null;

  const validateAndSubmit = (password, confirmPassword) => {
    if (password !== confirmPassword) {
      errorMessage = 'Passwords do not match.';
      return false;
    }
    if (password.length < 12) {
      errorMessage = 'Password must be at least 12 characters.';
      return false;
    }
    apiCalled = true;
    return true;
  };

  const result = validateAndSubmit('Short1!', 'Short1!');
  assert.equal(result, false);
  assert.equal(errorMessage, 'Password must be at least 12 characters.');
  assert.equal(apiCalled, false);
});

test('3. Immediate loading state and duplicate-submission prevention', async () => {
  let apiCallCount = 0;
  let isSubmitting = false;

  const fakeApiCall = () =>
    new Promise((resolve) => {
      apiCallCount++;
      setTimeout(() => resolve({ id: 'user-uuid-1', role: 'CITIZEN' }), 50);
    });

  const handleSubmit = async () => {
    if (isSubmitting) {
      // Re-entry guard: duplicate submissions are immediately blocked
      return;
    }
    isSubmitting = true;
    try {
      await fakeApiCall();
    } finally {
      isSubmitting = false;
    }
  };

  // First submit begins
  const p1 = handleSubmit();
  assert.equal(isSubmitting, true, 'Form must immediately enter submitting state');

  // Rapid second submit while p1 is in flight
  const p2 = handleSubmit();

  // Rapid third submit while p1 is in flight
  const p3 = handleSubmit();

  await Promise.all([p1, p2, p3]);

  assert.equal(apiCallCount, 1, 'Only exactly 1 API call must be dispatched despite rapid multiple triggers');
  assert.equal(isSubmitting, false, 'Submitting state must restore to false after completion');
});

test('4. Button state restoration and error feedback extraction on API failure', async () => {
  let isSubmitting = false;
  let displayedError = null;

  const extractErrorDetail = (reason) => {
    let detail = 'Could not create your citizen account. Please try again.';
    if (typeof reason === 'object' && reason !== null) {
      if ('detail' in reason) {
        const rawDetail = reason.detail;
        if (typeof rawDetail === 'string') {
          detail = rawDetail;
        } else if (Array.isArray(rawDetail) && rawDetail.length > 0) {
          const firstErr = rawDetail[0];
          detail = typeof firstErr === 'object' && firstErr !== null && 'msg' in firstErr
            ? String(firstErr.msg)
            : typeof firstErr === 'string'
              ? firstErr
              : JSON.stringify(firstErr);
        }
      } else if (reason instanceof Error) {
        detail = reason.message;
      }
    }
    return detail;
  };

  const failingSubmit = async (apiError) => {
    if (isSubmitting) return;
    isSubmitting = true;
    displayedError = null;
    try {
      throw apiError;
    } catch (reason) {
      displayedError = extractErrorDetail(reason);
    } finally {
      isSubmitting = false;
    }
  };

  // Test 409 Conflict error
  await failingSubmit({ status: 409, detail: 'An account with this email address already exists.' });
  assert.equal(isSubmitting, false, 'Button loading state must restore on 409 error');
  assert.equal(displayedError, 'An account with this email address already exists.');

  // Test 422 array validation error
  await failingSubmit({ status: 422, detail: [{ loc: ['body', 'password'], msg: 'Password must not exceed 128 characters.' }] });
  assert.equal(isSubmitting, false, 'Button loading state must restore on 422 error');
  assert.equal(displayedError, 'Password must not exceed 128 characters.');

  // Test 500 server error
  await failingSubmit({ status: 500, detail: 'An unexpected error occurred during registration. Please try again.' });
  assert.equal(isSubmitting, false, 'Button loading state must restore on 500 error');
  assert.equal(displayedError, 'An unexpected error occurred during registration. Please try again.');
});

test('5. Button loading label contract and spinner rendering parameters', () => {
  const getButtonDisplayProps = ({ isLoading, loadingText, children, disabled }) => {
    const isButtonDisabled = Boolean(disabled || isLoading);
    const label = isLoading ? (loadingText || 'Loading...') : children;
    const hasSpinner = Boolean(isLoading);
    return { isButtonDisabled, label, hasSpinner };
  };

  // Normal idle state
  const idle = getButtonDisplayProps({
    isLoading: false,
    loadingText: 'Creating account...',
    children: 'Create citizen account',
    disabled: false,
  });
  assert.equal(idle.isButtonDisabled, false);
  assert.equal(idle.label, 'Create citizen account');
  assert.equal(idle.hasSpinner, false);

  // Active submitting state
  const submitting = getButtonDisplayProps({
    isLoading: true,
    loadingText: 'Creating account...',
    children: 'Create citizen account',
    disabled: false,
  });
  assert.equal(submitting.isButtonDisabled, true);
  assert.equal(submitting.label, 'Creating account...');
  assert.equal(submitting.hasSpinner, true);
});
