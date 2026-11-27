/**
 * Utility to stamp civic complaint evidence photos with an embedded watermark
 * including NammaClean civic audit branding, GPS coordinates, accuracy, and timestamp.
 */

export interface WatermarkOptions {
  latitude: number;
  longitude: number;
  accuracy?: number | null;
  localityName?: string;
  timestamp?: Date;
}

export interface WatermarkedEvidence {
  originalFile: File;
  watermarkedFile: File;
  previewUrl: string;
}

export async function embedWatermark(
  file: File,
  options: WatermarkOptions
): Promise<WatermarkedEvidence> {
  return new Promise((resolve, reject) => {
    const objectUrl = URL.createObjectURL(file);
    const img = new Image();

    img.onload = () => {
      URL.revokeObjectURL(objectUrl);

      try {
        const canvas = document.createElement('canvas');
        let width = img.naturalWidth || 1280;
        let height = img.naturalHeight || 720;

        // Cap dimensions at 1920 to keep upload sizes reasonable while retaining high resolution
        const maxDim = 1920;
        if (width > maxDim || height > maxDim) {
          if (width > height) {
            height = Math.round((height * maxDim) / width);
            width = maxDim;
          } else {
            width = Math.round((width * maxDim) / height);
            height = maxDim;
          }
        }

        canvas.width = width;
        canvas.height = height;

        const ctx = canvas.getContext('2d');
        if (!ctx) {
          throw new Error('Canvas 2D context not available');
        }

        // 1. Draw base photo
        ctx.drawImage(img, 0, 0, width, height);

        // 2. Compute watermark banner height (proportional to image size)
        const bannerHeight = Math.max(88, Math.round(height * 0.12));
        const bannerY = height - bannerHeight;

        // 3. Dark semi-transparent gradient background for high contrast
        const gradient = ctx.createLinearGradient(0, bannerY, 0, height);
        gradient.addColorStop(0, 'rgba(10, 25, 16, 0.82)');
        gradient.addColorStop(1, 'rgba(4, 14, 8, 0.96)');
        ctx.fillStyle = gradient;
        ctx.fillRect(0, bannerY, width, bannerHeight);

        // 4. Accent green top border line
        ctx.fillStyle = '#22C55E';
        ctx.fillRect(0, bannerY, width, Math.max(3, Math.round(height * 0.005)));

        // 5. Typography sizing
        const titleFontSize = Math.max(15, Math.round(bannerHeight * 0.24));
        const subFontSize = Math.max(11, Math.round(bannerHeight * 0.17));
        const paddingX = Math.max(16, Math.round(width * 0.02));

        // 6. Left side: Branding & Classification
        const leftTitleY = bannerY + Math.round(bannerHeight * 0.42);
        const leftSubY = bannerY + Math.round(bannerHeight * 0.78);

        ctx.textAlign = 'left';

        // Title
        ctx.fillStyle = '#4ADE80'; // Bright civic green
        ctx.font = `bold ${titleFontSize}px system-ui, -apple-system, sans-serif`;
        ctx.fillText('NAMMACLEAN • BBMP CIVIC AUDIT', paddingX, leftTitleY);

        // Subtitle
        ctx.fillStyle = '#F3F4F6';
        ctx.font = `600 ${subFontSize}px system-ui, -apple-system, sans-serif`;
        ctx.fillText('Official Geo-tagged Evidence Photo', paddingX, leftSubY);

        // 7. Right side: GPS Coordinates & Timestamp
        const dateObj = options.timestamp || new Date();
        const dateStr = dateObj.toLocaleString('en-IN', {
          timeZone: 'Asia/Kolkata',
          year: 'numeric',
          month: 'short',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
          hour12: false,
        });

        const latStr = `${Math.abs(options.latitude).toFixed(5)}° ${options.latitude >= 0 ? 'N' : 'S'}`;
        const lonStr = `${Math.abs(options.longitude).toFixed(5)}° ${options.longitude >= 0 ? 'E' : 'W'}`;
        const accStr =
          typeof options.accuracy === 'number' && Number.isFinite(options.accuracy)
            ? ` (±${Math.round(options.accuracy)}m)`
            : '';

        const rightAlignX = width - paddingX;
        ctx.textAlign = 'right';

        // Coordinates row
        ctx.fillStyle = '#FFFFFF';
        ctx.font = `bold ${subFontSize}px ui-monospace, SFMono-Regular, Menlo, monospace`;
        ctx.fillText(`GPS: ${latStr}, ${lonStr}${accStr}`, rightAlignX, leftTitleY);

        // Timestamp & Locality row
        ctx.fillStyle = '#D1D5DB';
        ctx.font = `500 ${subFontSize}px ui-monospace, SFMono-Regular, Menlo, monospace`;
        const localityLabel = options.localityName ? ` • ${options.localityName}` : '';
        ctx.fillText(`${dateStr} IST${localityLabel}`, rightAlignX, leftSubY);

        // 8. Convert to JPEG Blob
        canvas.toBlob(
          (blob) => {
            if (!blob) {
              reject(new Error('Failed to generate watermarked image blob'));
              return;
            }
            const cleanName = file.name.replace(/\.[^/.]+$/, '');
            const watermarkedFile = new File([blob], `${cleanName}_geotagged.jpg`, {
              type: 'image/jpeg',
              lastModified: Date.now(),
            });
            const previewUrl = URL.createObjectURL(blob);
            resolve({
              originalFile: file,
              watermarkedFile,
              previewUrl,
            });
          },
          'image/jpeg',
          0.92
        );
      } catch (err) {
        reject(err);
      }
    };

    img.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      reject(new Error(`Failed to load image for watermarking: ${file.name}`));
    };

    img.src = objectUrl;
  });
}
