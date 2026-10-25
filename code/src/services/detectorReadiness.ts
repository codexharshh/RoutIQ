export type DetectorReadiness = {
  status: string;
  labels: string;
  inference_tested: boolean;
};

export function detectorReadinessMessage(readiness: DetectorReadiness): string {
  if (readiness.inference_tested) return 'The vision service reports a successfully verified real inference check.';
  const explanations: Record<string, string> = {
    vision_unavailable: 'Django could not reach the FastAPI vision service. Start the vision service and confirm ROUTIQ_VISION_URL.',
    vision_timeout: 'The FastAPI readiness request timed out. Check that the service is responsive, then refresh this page.',
    invalid_readiness_response: 'FastAPI responded, but its readiness report was invalid. Review the service configuration and logs.',
    disabled: 'The vision service is available, but detection is disabled. Configure an authorized YOLOv8 model to enable it.',
    test_backend_only: 'The vision service is configured for a test-only backend. Configure a supported real model before using detection.',
    missing_weights_path: 'Detection is enabled but no model weights path is configured.',
    weights_not_found: 'The configured model weights are unavailable. Check the authorized model path on the vision-service host.',
    invalid_weights_path: 'The configured model weights path is invalid or inaccessible to the vision service.',
    incompatible_labels: 'The loaded model labels do not match RoutIQ damage classes. Select a compatible model.',
    dependency_missing: 'A required inference dependency is missing from the vision-service environment.',
    model_load_failed: 'The model could not be loaded. Review the vision-service configuration and logs.',
    ready_to_test: 'The model loaded with compatible labels. This endpoint reports startup readiness; image inference is confirmed by a successful analysis request.',
    weights_present_unverified: 'A weights file is present, but model loading and real inference have not been verified.',
    model_loaded_labels_unavailable: 'The model loaded, but its class labels could not be verified.',
    invalid_configuration: 'The vision-service model configuration is invalid.',
    unsupported_backend: 'The configured detector backend is not supported.',
  };
  return explanations[readiness.status] ?? 'Detector readiness is not verified. Review the vision-service configuration.';
}
