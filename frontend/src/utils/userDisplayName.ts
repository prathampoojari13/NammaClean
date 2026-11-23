import type { User } from '../types';

/**
 * Resolves a safe display name for greeting the user.
 * 
 * Rules:
 * 1. If user has full_name, use it.
 * 2. If user has locality, use it.
 * 3. If user has email, extract and capitalize the local part cleanly.
 * 4. Fallback to fallbackName parameter if provided.
 * 5. Return null if no valid name can be resolved (caller should show neutral greeting).
 * 6. Never returns empty string, 'undefined', 'null', or hardcoded personal names.
 */
export function resolveUserDisplayName(
  user?: User | null,
  fallbackName?: string | null
): string | null {
  if (user) {
    if (user.full_name && typeof user.full_name === 'string' && user.full_name.trim().length > 0) {
      return user.full_name.trim();
    }
    if (user.locality && typeof user.locality === 'string' && user.locality.trim().length > 0) {
      return user.locality.trim();
    }
    if (user.email && typeof user.email === 'string') {
      const emailPrefix = user.email.split('@')[0];
      const cleaned = emailPrefix.replace(/[._-]/g, ' ').trim();
      if (cleaned.length > 0) {
        return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
      }
    }
  }

  if (fallbackName && typeof fallbackName === 'string' && fallbackName.trim().length > 0) {
    const emailPrefix = fallbackName.includes('@') ? fallbackName.split('@')[0] : fallbackName;
    const cleaned = emailPrefix.replace(/[._-]/g, ' ').trim();
    if (cleaned.length > 0) {
      return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
    }
  }

  return null;
}
