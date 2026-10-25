import React, { useState } from 'react';
import { API_BASE_URL } from '../config';
import './UploadPage.css';

interface UploadPageProps {
  onNavigateToMap: () => void;
}

const UploadPage: React.FC<UploadPageProps> = ({ onNavigateToMap }) => {
  const [videoFiles, setVideoFiles] = useState<FileList | null>(null);
  const [gpsFiles, setGpsFiles] = useState<FileList | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingStatus, setProcessingStatus] = useState<string>('');
  const [distanceThreshold, setDistanceThreshold] = useState<number>(2.5);

  const authHeaders = (): Record<string, string> => {
    const token = localStorage.getItem('routiq_access_token');
    return token ? { Authorization: `Bearer ${token}` } : {};
  };

  const handleVideoUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    setVideoFiles(event.target.files);
  };

  const handleGpsUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    setGpsFiles(event.target.files);
  };

  const uploadFiles = async (files: FileList, endpoint: string) => {
    const formData = new FormData();
    Array.from(files).forEach((file) => {
      formData.append('files', file);
    });

    const response = await fetch(endpoint, {
      method: 'POST',
      headers: authHeaders(),
      body: formData,
    });

    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = typeof payload?.detail === 'string' ? payload.detail : `HTTP ${response.status}`;
      throw new Error(`Upload failed: ${detail}`);
    }
    return payload;
  };

  const processVideo = async (videoId: string, gpsBatchId: string) => {
    const response = await fetch(`${API_BASE_URL}/process-video/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders(),
      },
      body: JSON.stringify({
        video_id: videoId,
        gps_batch_id: gpsBatchId,
        distance_threshold: distanceThreshold,
      }),
    });

    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = typeof payload?.detail === 'string' ? payload.detail : `HTTP ${response.status}`;
      throw new Error(`Processing failed: ${detail}`);
    }
    return payload;
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();

    if (!videoFiles || videoFiles.length === 0) {
      setProcessingStatus('Please select one or more video files.');
      alert('Please select one or more video files.');
      return;
    }

    if (!gpsFiles || gpsFiles.length === 0) {
      setProcessingStatus('GPS trace files (.git, .txt, .nmea, .log) are required to determine road-damage locations from dashcam video timestamps. Browser location is never substituted for missing dashcam GPS data.');
      alert('GPS trace files are required for dashcam processing to determine road-damage locations.');
      return;
    }

    setIsProcessing(true);
    setProcessingStatus('Uploading files...');

    try {
      // Upload video files
      setProcessingStatus('Uploading video files...');
      const videoUploadResult = await uploadFiles(videoFiles, `${API_BASE_URL}/upload-videos/`);

      // Upload GPS files
      setProcessingStatus('Uploading GPS files...');
      const gpsUploadResult = await uploadFiles(gpsFiles, `${API_BASE_URL}/upload-gps/`);

      // Process each video with corresponding GPS data
      const videoResults = [];
      for (const videoId of videoUploadResult.uploaded_files) {
        setProcessingStatus('Processing uploaded video...');
        const result = await processVideo(videoId, gpsUploadResult.upload_directory);
        videoResults.push(result);
      }

      setProcessingStatus('Processing completed. Review the map for saved detections with matched GPS coordinates.');

      // Auto-navigate to map after 2 seconds
      setTimeout(() => {
        onNavigateToMap();
      }, 2000);

    } catch (error) {
      console.error('Error processing files:', error);
      setProcessingStatus(`Error: ${error instanceof Error ? error.message : 'Unknown error'}`);
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <div className="upload-page">
      <div className="upload-container">
        <div className="upload-header">
          <h1>RoutIQ Dashcam & GPS Processing</h1>
          <p>Process dashcam video and GPS traces into road-damage records</p>
          <button
            className="nav-button"
            onClick={onNavigateToMap}
            disabled={isProcessing}
          >
            ← Back to Map
          </button>
        </div>

        <form onSubmit={handleSubmit} className="upload-form">
          <div className="file-input-section">
            <h3>Video Files</h3>
            <p>Select one or more MP4 dashcam videos</p>
            <input
              type="file"
              accept=".mp4,.avi,.mov"
              multiple
              onChange={handleVideoUpload}
              className="file-input"
              disabled={isProcessing}
            />
            {videoFiles && (
              <div className="file-list">
                <p>Selected videos:</p>
                <ul>
                  {Array.from(videoFiles).map((file, index) => (
                    <li key={index}>{file.name} ({(file.size / 1024 / 1024).toFixed(1)} MB)</li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          <div className="file-input-section">
            <h3>GPS Files</h3>
            <p>Select the corresponding GPS trace files (.git, .txt, .nmea, .log)</p>
            <p style={{ fontSize: '0.85rem', color: '#64748b', margin: '0 0 1rem 0' }}>
              Road-damage locations are mapped strictly from synchronized dashcam GPS logs. Browser device location is never substituted for missing dashcam GPS data.
            </p>
            <input
              type="file"
              accept=".git,.txt,.nmea,.log"
              multiple
              onChange={handleGpsUpload}
              className="file-input"
              disabled={isProcessing}
            />
            {gpsFiles && (
              <div className="file-list">
                <p>Selected GPS files:</p>
                <ul>
                  {Array.from(gpsFiles).map((file, index) => (
                    <li key={index}>{file.name} ({(file.size / 1024).toFixed(1)} KB)</li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          <div className="settings-section">
            <h3>Processing Settings</h3>
            <div className="setting-item">
              <label htmlFor="distance-threshold">
                Distance Threshold (meters):
                <span className="setting-help">
                  Minimum distance between detected potholes to avoid duplicates
                </span>
              </label>
              <input
                id="distance-threshold"
                type="number"
                min="0.5"
                max="10"
                step="0.5"
                value={distanceThreshold}
                onChange={(e) => setDistanceThreshold(parseFloat(e.target.value))}
                disabled={isProcessing}
              />
            </div>
          </div>

          <div className="submit-section">
            <button
              type="submit"
              className="submit-button"
              disabled={isProcessing || !videoFiles || !gpsFiles}
            >
              {isProcessing ? 'Processing…' : 'Process videos'}
            </button>
          </div>
        </form>

        {processingStatus && (
          <div className={`status-message ${isProcessing ? 'processing' : 'complete'}`}>
            <p>{processingStatus}</p>
            {isProcessing && (
              <div className="progress-bar">
                <div className="progress-bar-fill"></div>
              </div>
            )}
          </div>
        )}

        <div className="info-section">
          <h3>How it works</h3>
          <ol>
            <li>Upload your dashcam video files (MP4 format recommended)</li>
            <li>Upload corresponding GPS .git files from your dashcam</li>
            <li>The system will process videos using AI to detect potholes</li>
            <li>GPS coordinates will be matched with detected potholes</li>
            <li>Results will be automatically added to the pothole database</li>
            <li>You'll be redirected to the map to view the new data</li>
          </ol>
        </div>
      </div>
    </div>
  );
};

export default UploadPage;
