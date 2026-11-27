import React, { useState, useEffect } from 'react';
import {
  X,
  Lock,
  CheckCircle2,
  AlertCircle,
  Edit3,
} from 'lucide-react';
import { apiClient } from '../../api/client';
import type { User as UserType } from '../../types';

interface UserProfileModalProps {
  isOpen: boolean;
  onClose: () => void;
  currentUser: UserType | null;
  onProfileUpdated?: (updatedUser: UserType) => void;
}

export const UserProfileModal: React.FC<UserProfileModalProps> = ({
  isOpen,
  onClose,
  currentUser,
  onProfileUpdated,
}) => {
  const [isEditing, setIsEditing] = useState(false);
  const [formData, setFormData] = useState({
    full_name: '',
    phone_number: '',
    locality: '',
    address: '',
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (currentUser) {
      setFormData({
        full_name: currentUser.full_name || '',
        phone_number: currentUser.phone_number || '',
        locality: currentUser.locality || '',
        address: currentUser.address || '',
      });
      setIsEditing(false);
      setError(null);
      setSuccess(null);
    }
  }, [currentUser, isOpen]);

  if (!isOpen || !currentUser) return null;

  const handleCancelEdit = () => {
    if (currentUser) {
      setFormData({
        full_name: currentUser.full_name || '',
        phone_number: currentUser.phone_number || '',
        locality: currentUser.locality || '',
        address: currentUser.address || '',
      });
    }
    setIsEditing(false);
    setError(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setError(null);
    setSuccess(null);

    // Validate phone number if entered
    if (formData.phone_number.trim()) {
      const cleanPhone = formData.phone_number.replace(/[\s\-\(\)\+]/g, '');
      if (!/^\d{10,15}$/.test(cleanPhone)) {
        setError('Phone number must contain between 10 and 15 digits.');
        setIsSubmitting(false);
        return;
      }
    }

    try {
      const payload: Record<string, string | null> = {
        full_name: formData.full_name.trim() || null,
        phone_number: formData.phone_number.trim() || null,
        locality: formData.locality.trim() || null,
        address: formData.address.trim() || null,
      };

      const updated = await apiClient.patch<UserType>('/users/me', payload);
      setSuccess('Profile updated successfully!');
      onProfileUpdated?.(updated);
      setTimeout(() => {
        onClose();
      }, 1000);
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || 'Failed to update profile.';
      setError(typeof msg === 'string' ? msg : JSON.stringify(msg));
    } finally {
      setIsSubmitting(false);
    }
  };

  const roleNameMap: Record<string, string> = {
    CITIZEN: 'Citizen Resident',
    SANITATION_WORKER: 'Pourakarmika (Sanitation Worker)',
    DRIVER: 'Fleet Operations Driver',
    WARD_SUPERVISOR: 'Ward Supervisor',
    MUNICIPAL_ADMIN: 'Municipal Administrator',
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.5)',
        backdropFilter: 'blur(3px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 100,
        padding: '1rem',
      }}
    >
      <div
        style={{
          backgroundColor: '#FFFFFF',
          borderRadius: '16px',
          maxWidth: '520px',
          width: '100%',
          overflow: 'hidden',
          boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1), 0 10px 10px -5px rgba(0,0,0,0.04)',
          border: '1px solid #D5E3D7',
          display: 'flex',
          flexDirection: 'column',
          maxHeight: '90vh',
        }}
      >
        {/* Modal Header */}
        <div
          style={{
            backgroundColor: '#0E3A28',
            color: '#FFFFFF',
            padding: '1.25rem 1.5rem',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <div
              style={{
                width: '40px',
                height: '40px',
                borderRadius: '50%',
                backgroundColor: '#1E5E41',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontWeight: 800,
                color: '#FFFFFF',
                fontSize: '1rem',
              }}
            >
              {currentUser.full_name
                ? currentUser.full_name.slice(0, 2).toUpperCase()
                : currentUser.email.slice(0, 2).toUpperCase()}
            </div>
            <div>
              <h3 style={{ margin: 0, fontSize: '1.15rem', fontWeight: 750 }}>
                {currentUser.full_name || 'My Profile'}
              </h3>
              <p style={{ margin: '2px 0 0 0', fontSize: '0.76rem', color: '#A3D9BA' }}>
                {roleNameMap[currentUser.role] || currentUser.role}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            style={{ background: 'none', border: 'none', color: '#FFFFFF', cursor: 'pointer', padding: '4px' }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Modal Form */}
        <form onSubmit={handleSubmit} style={{ padding: '1.5rem', overflowY: 'auto' }}>
          {error && (
            <div
              style={{
                backgroundColor: '#FEF2F2',
                border: '1px solid #FCA5A5',
                color: '#991B1B',
                padding: '0.65rem 0.85rem',
                borderRadius: '8px',
                fontSize: '0.82rem',
                marginBottom: '1rem',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
              }}
            >
              <AlertCircle size={15} />
              <span>{error}</span>
            </div>
          )}

          {success && (
            <div
              style={{
                backgroundColor: '#ECFDF5',
                border: '1px solid #6EE7B7',
                color: '#065F46',
                padding: '0.65rem 0.85rem',
                borderRadius: '8px',
                fontSize: '0.82rem',
                marginBottom: '1rem',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
              }}
            >
              <CheckCircle2 size={15} />
              <span>{success}</span>
            </div>
          )}

          {/* Section: Locked Institutional Credentials */}
          <div
            style={{
              backgroundColor: '#F8FAFC',
              borderRadius: '10px',
              padding: '1rem',
              border: '1px solid #E2E8F0',
              marginBottom: '1.25rem',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.65rem' }}>
              <Lock size={13} color="#64748B" />
              <span style={{ fontSize: '0.76rem', fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                Institutional Governance Attributes (Locked)
              </span>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.65rem' }}>
              <div>
                <span style={{ fontSize: '0.72rem', color: '#64748B', display: 'block' }}>Official Email</span>
                <span style={{ fontSize: '0.82rem', fontWeight: 650, color: '#1E293B', wordBreak: 'break-all' }}>
                  {currentUser.email}
                </span>
              </div>

              <div>
                <span style={{ fontSize: '0.72rem', color: '#64748B', display: 'block' }}>Official ID</span>
                <span style={{ fontSize: '0.82rem', fontWeight: 750, color: currentUser.official_id ? '#0369A1' : '#92400E' }}>
                  {currentUser.official_id || 'Pending Official ID'}
                </span>
              </div>

              <div>
                <span style={{ fontSize: '0.72rem', color: '#64748B', display: 'block' }}>System Role</span>
                <span style={{ fontSize: '0.82rem', fontWeight: 650, color: '#1E293B' }}>
                  {currentUser.role}
                </span>
              </div>

              <div>
                <span style={{ fontSize: '0.72rem', color: '#64748B', display: 'block' }}>Account Status</span>
                <span
                  style={{
                    display: 'inline-block',
                    padding: '1px 6px',
                    borderRadius: '999px',
                    fontSize: '0.7rem',
                    fontWeight: 700,
                    backgroundColor: '#D1FAE5',
                    color: '#065F46',
                  }}
                >
                  {currentUser.status}
                </span>
              </div>
            </div>
          </div>

          {/* Section: Personal Details (View Mode vs Edit Mode) */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.9rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '2px' }}>
              <span style={{ fontSize: '0.8rem', fontWeight: 750, color: '#1E293B', textTransform: 'uppercase', letterSpacing: '0.03em' }}>
                Personal Profile Information
              </span>
              {!isEditing && (
                <button
                  type="button"
                  onClick={() => setIsEditing(true)}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '0.35rem',
                    backgroundColor: '#F0FDF4',
                    border: '1px solid #86EFAC',
                    color: '#166534',
                    padding: '3px 10px',
                    borderRadius: '6px',
                    fontSize: '0.78rem',
                    fontWeight: 700,
                    cursor: 'pointer',
                  }}
                >
                  <Edit3 size={13} />
                  <span>Edit Profile</span>
                </button>
              )}
            </div>

            {isEditing ? (
              <>
                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: '#334155', marginBottom: '4px' }}>
                    Full Legal Name
                  </label>
                  <input
                    type="text"
                    placeholder="Enter your full name"
                    value={formData.full_name}
                    onChange={(e) => setFormData({ ...formData, full_name: e.target.value })}
                    style={{
                      width: '100%',
                      padding: '8px 10px',
                      borderRadius: '7px',
                      border: '1px solid #CBD5E1',
                      fontSize: '0.85rem',
                      boxSizing: 'border-box',
                    }}
                  />
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: '#334155', marginBottom: '4px' }}>
                    Contact Phone Number (10–15 digits)
                  </label>
                  <input
                    type="tel"
                    placeholder="e.g. +91 98450 12345"
                    value={formData.phone_number}
                    onChange={(e) => setFormData({ ...formData, phone_number: e.target.value })}
                    style={{
                      width: '100%',
                      padding: '8px 10px',
                      borderRadius: '7px',
                      border: '1px solid #CBD5E1',
                      fontSize: '0.85rem',
                      boxSizing: 'border-box',
                    }}
                  />
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: '#334155', marginBottom: '4px' }}>
                    Locality / Residential Area
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. Yelahanka Satellite Town, Avalahalli, Indiranagar"
                    value={formData.locality}
                    onChange={(e) => setFormData({ ...formData, locality: e.target.value })}
                    style={{
                      width: '100%',
                      padding: '8px 10px',
                      borderRadius: '7px',
                      border: '1px solid #CBD5E1',
                      fontSize: '0.85rem',
                      boxSizing: 'border-box',
                    }}
                  />
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: '#334155', marginBottom: '4px' }}>
                    Street / Residential Address
                  </label>
                  <textarea
                    rows={2}
                    placeholder="House / Street address in Bengaluru"
                    value={formData.address}
                    onChange={(e) => setFormData({ ...formData, address: e.target.value })}
                    style={{
                      width: '100%',
                      padding: '8px 10px',
                      borderRadius: '7px',
                      border: '1px solid #CBD5E1',
                      fontSize: '0.85rem',
                      boxSizing: 'border-box',
                      resize: 'vertical',
                    }}
                  />
                </div>
              </>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.85rem', backgroundColor: '#F8FAFC', padding: '1rem', borderRadius: '8px', border: '1px solid #E2E8F0' }}>
                <div>
                  <span style={{ fontSize: '0.72rem', color: '#64748B', display: 'block' }}>Full Name</span>
                  <span style={{ fontSize: '0.85rem', fontWeight: 650, color: '#1E293B' }}>
                    {formData.full_name || 'Not provided'}
                  </span>
                </div>
                <div>
                  <span style={{ fontSize: '0.72rem', color: '#64748B', display: 'block' }}>Phone Number</span>
                  <span style={{ fontSize: '0.85rem', fontWeight: 650, color: '#1E293B' }}>
                    {formData.phone_number || 'Not provided'}
                  </span>
                </div>
                <div>
                  <span style={{ fontSize: '0.72rem', color: '#64748B', display: 'block' }}>Locality</span>
                  <span style={{ fontSize: '0.85rem', fontWeight: 650, color: '#1E293B' }}>
                    {formData.locality || 'Not provided'}
                  </span>
                </div>
                <div>
                  <span style={{ fontSize: '0.72rem', color: '#64748B', display: 'block' }}>Residential Address</span>
                  <span style={{ fontSize: '0.85rem', fontWeight: 650, color: '#1E293B' }}>
                    {formData.address || 'Not provided'}
                  </span>
                </div>
              </div>
            )}
          </div>

          <div style={{ marginTop: '1.5rem', display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '0.75rem' }}>
            {isEditing ? (
              <>
                <button
                  type="button"
                  onClick={handleCancelEdit}
                  disabled={isSubmitting}
                  style={{
                    padding: '8px 16px',
                    borderRadius: '7px',
                    border: '1px solid #CBD5E1',
                    backgroundColor: '#FFFFFF',
                    color: '#475569',
                    fontSize: '0.85rem',
                    fontWeight: 650,
                    cursor: 'pointer',
                  }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  style={{
                    padding: '8px 20px',
                    borderRadius: '7px',
                    border: 'none',
                    backgroundColor: '#2E7D32',
                    color: '#FFFFFF',
                    fontSize: '0.85rem',
                    fontWeight: 700,
                    cursor: 'pointer',
                    boxShadow: '0 2px 6px rgba(46,125,50,0.25)',
                  }}
                >
                  {isSubmitting ? 'Saving Changes...' : 'Save Changes'}
                </button>
              </>
            ) : (
              <button
                type="button"
                onClick={onClose}
                style={{
                  padding: '8px 20px',
                  borderRadius: '7px',
                  border: '1px solid #CBD5E1',
                  backgroundColor: '#FFFFFF',
                  color: '#334155',
                  fontSize: '0.85rem',
                  fontWeight: 700,
                  cursor: 'pointer',
                }}
              >
                Close
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
};
