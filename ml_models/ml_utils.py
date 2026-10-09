"""
ML Utilities for Goat Detection

This module provides server-side ML inference for goat detection.
Supports TensorFlow/Keras, PyTorch, and scikit-learn models.

Note: Your trained model runs entirely in Python (NO conversion needed!)
"""

import numpy as np
import os
import requests
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
from typing import List, Dict, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class BaseDetector:
    """Base class for all detectors"""
    
    def __init__(self, model_path: str, confidence_threshold: float = 0.5):
        self.model_path = model_path
        self.confidence_threshold = confidence_threshold
        self.model = None
        self.input_shape = (640, 640)
    
    def preprocess(self, image: np.ndarray) -> np.ndarray:
        """Preprocess image for model input"""
        raise NotImplementedError
    
    def postprocess(self, outputs: np.ndarray) -> List[Dict]:
        """Postprocess model outputs to detections"""
        raise NotImplementedError
    
    def detect(self, image: np.ndarray) -> Dict:
        """Main detection method"""
        raise NotImplementedError
    
    @staticmethod
    def apply_nms(detections: List[Dict], iou_threshold: float = 0.45) -> List[Dict]:
        """
        Apply Non-Maximum Suppression to remove overlapping boxes.
        
        Args:
            detections: List of detection dicts with 'bbox' and 'confidence'
            iou_threshold: IoU threshold for NMS
            
        Returns:
            Filtered list of detections
        """
        if not detections:
            return []
        
        # Sort by confidence (descending)
        detections = sorted(detections, key=lambda x: x['confidence'], reverse=True)
        
        kept = []
        while detections:
            # Keep the detection with highest confidence
            best = detections.pop(0)
            kept.append(best)
            
            # Remove overlapping boxes
            detections = [
                d for d in detections
                if BaseDetector._calculate_iou(best['bbox'], d['bbox']) < iou_threshold
            ]
        
        return kept
    
    @staticmethod
    def _calculate_iou(box1: Dict, box2: Dict) -> float:
        """Calculate Intersection over Union (IoU) between two boxes"""
        x1_min = box1['x']
        y1_min = box1['y']
        x1_max = box1['x'] + box1['width']
        y1_max = box1['y'] + box1['height']
        
        x2_min = box2['x']
        y2_min = box2['y']
        x2_max = box2['x'] + box2['width']
        y2_max = box2['y'] + box2['height']
        
        # Calculate intersection area
        inter_x_min = max(x1_min, x2_min)
        inter_y_min = max(y1_min, y2_min)
        inter_x_max = min(x1_max, x2_max)
        inter_y_max = min(y1_max, y2_max)
        
        if inter_x_max < inter_x_min or inter_y_max < inter_y_min:
            return 0.0
        
        inter_area = (inter_x_max - inter_x_min) * (inter_y_max - inter_y_min)
        
        # Calculate union area
        box1_area = box1['width'] * box1['height']
        box2_area = box2['width'] * box2['height']
        union_area = box1_area + box2_area - inter_area
        
        if union_area == 0:
            return 0.0
        
        return inter_area / union_area


class TensorFlowDetector(BaseDetector):
    """
    TensorFlow/Keras-based goat detection.
    
    Supports .h5, .keras, and SavedModel formats.
    NO conversion needed - use your trained model directly!
    """
    
    def __init__(self, model_path: str, confidence_threshold: float = 0.5, use_gpu: bool = False):
        super().__init__(model_path, confidence_threshold)
        
        try:
            import tensorflow as tf
            
            # Configure GPU usage
            if not use_gpu:
                tf.config.set_visible_devices([], 'GPU')
            
            # Load TensorFlow/Keras model
            self.model = tf.keras.models.load_model(model_path)
            logger.info(f"✅ TensorFlow model loaded: {model_path}")
            logger.info(f"   Input shape: {self.model.input_shape}")
            logger.info(f"   Output shape: {self.model.output_shape}")
            
        except ImportError:
            logger.error("TensorFlow not installed. Install with: pip install tensorflow")
            raise
        except Exception as e:
            logger.error(f"Failed to load TensorFlow model: {e}")
            raise
    
    def preprocess(self, image: np.ndarray) -> np.ndarray:
        """Preprocess image for TensorFlow model"""
        # Resize to model input size
        img = cv2.resize(image, self.input_shape)
        
        # Convert BGR to RGB
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        
        # Normalize to [0, 1]
        img = img.astype(np.float32) / 255.0
        
        # Add batch dimension: (1, H, W, C)
        img = np.expand_dims(img, axis=0)
        
        return img
    
    def postprocess(self, outputs: np.ndarray, original_shape: Tuple[int, int]) -> List[Dict]:
        """
        Process model outputs to detection boxes.
        
        Assumes YOLO-like output format: [batch, num_boxes, 6]
        Where each box is: [x_center, y_center, width, height, confidence, class]
        
        Adjust this method based on your actual model output format!
        """
        detections = []
        orig_h, orig_w = original_shape[:2]
        
        # Get first batch
        predictions = outputs[0]
        
        for pred in predictions:
            # Handle different output formats
            if len(pred) >= 6:
                x_center, y_center, width, height, confidence, class_id = pred[:6]
            elif len(pred) >= 5:
                x_center, y_center, width, height, confidence = pred[:5]
                class_id = 0  # Assume single class (goat)
            else:
                continue
            
            if confidence >= self.confidence_threshold:
                # Convert from center format to corner format
                x = (x_center - width / 2) * orig_w
                y = (y_center - height / 2) * orig_h
                w = width * orig_w
                h = height * orig_h
                
                detections.append({
                    'bbox': {
                        'x': float(max(0, x)),
                        'y': float(max(0, y)),
                        'width': float(min(w, orig_w - x)),
                        'height': float(min(h, orig_h - y))
                    },
                    'confidence': float(confidence),
                    'class': int(class_id),
                    'label': 'goat'
                })
        
        # Apply NMS
        detections = self.apply_nms(detections)
        
        return detections
    
    def detect(self, image: np.ndarray) -> Dict:
        """Run goat detection on image"""
        original_shape = image.shape
        
        # Preprocess
        input_tensor = self.preprocess(image)
        
        # Run inference
        outputs = self.model.predict(input_tensor, verbose=0)
        
        # Postprocess
        detections = self.postprocess(outputs, original_shape)
        
        return {
            'count': len(detections),
            'detections': detections,
            'confidence': max([d['confidence'] for d in detections]) if detections else 0.0
        }


class PyTorchDetector(BaseDetector):
    """
    PyTorch-based goat detection.
    
    Supports .pt and .pth model formats.
    NO conversion needed!
    """
    
    def __init__(self, model_path: str, confidence_threshold: float = 0.5, use_gpu: bool = False):
        super().__init__(model_path, confidence_threshold)
        
        try:
            import torch
            
            self.device = torch.device('cuda' if use_gpu and torch.cuda.is_available() else 'cpu')
            
            # Load PyTorch model
            self.model = torch.load(model_path, map_location=self.device)
            self.model.eval()  # Set to evaluation mode
            
            logger.info(f"✅ PyTorch model loaded: {model_path}")
            logger.info(f"   Device: {self.device}")
            
        except ImportError:
            logger.error("PyTorch not installed. Install with: pip install torch")
            raise
        except Exception as e:
            logger.error(f"Failed to load PyTorch model: {e}")
            raise
    
    def preprocess(self, image: np.ndarray):
        """Preprocess image for PyTorch model"""
        import torch
        
        # Resize
        img = cv2.resize(image, self.input_shape)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = img.astype(np.float32) / 255.0
        
        # Convert to CHW format (PyTorch convention)
        img = img.transpose(2, 0, 1)
        
        # Convert to tensor
        img = torch.from_numpy(img).unsqueeze(0).to(self.device)
        
        return img
    
    def postprocess(self, outputs: np.ndarray, original_shape: Tuple[int, int]) -> List[Dict]:
        """Process PyTorch model outputs"""
        # Similar to TensorFlow postprocess
        # Adjust based on your model format
        return []
    
    def detect(self, image: np.ndarray) -> Dict:
        """Run goat detection on image"""
        import torch
        
        original_shape = image.shape
        input_tensor = self.preprocess(image)
        
        # Run inference
        with torch.no_grad():
            outputs = self.model(input_tensor)
        
        # Convert to numpy
        outputs_np = outputs.cpu().numpy()
        
        # Postprocess
        detections = self.postprocess(outputs_np, original_shape)
        
        return {
            'count': len(detections),
            'detections': detections,
            'confidence': max([d['confidence'] for d in detections]) if detections else 0.0
        }


class YOLOv8Detector(BaseDetector):
    """
    YOLOv8 (Ultralytics) goat detection.
    
    Uses ultralytics library for YOLOv8 inference.
    NO conversion needed - use your trained .pt model directly!
    """
    
    def __init__(self, model_path: str, confidence_threshold: float = 0.5, use_gpu: bool = False, **_unused):
        super().__init__(model_path, confidence_threshold)
        
        try:
            from ultralytics import YOLO
            
            # Load YOLOv8 model
            self.model = YOLO(model_path)
            
            # Set device
            if use_gpu:
                import torch
                if torch.cuda.is_available():
                    self.device = 'cuda'
                else:
                    logger.warning("GPU requested but not available, using CPU")
                    self.device = 'cpu'
            else:
                self.device = 'cpu'
            
            logger.info(f"✅ YOLOv8 model loaded: {model_path}")
            logger.info(f"   Device: {self.device}")
            logger.info(f"   Confidence threshold: {confidence_threshold}")
            
        except ImportError:
            logger.error("Ultralytics not installed. Install with: pip install ultralytics")
            raise
        except Exception as e:
            logger.error(f"Failed to load YOLOv8 model: {e}")
            raise
    
    def detect(self, image: np.ndarray) -> Dict:
        """
        Run YOLOv8 goat detection on image.
        
        Args:
            image: Input image in BGR format (OpenCV standard)
            
        Returns:
            Dict with detection results
        """
        try:
            # Run inference
            results = self.model.predict(
                image,
                conf=self.confidence_threshold,
                device=self.device,
                verbose=False
            )
            
            # Parse results
            detections = []
            
            if len(results) > 0:
                result = results[0]  # Get first result
                
                # Extract boxes
                if hasattr(result, 'boxes') and result.boxes is not None:
                    boxes = result.boxes
                    
                    for i in range(len(boxes)):
                        # Get box coordinates (xyxy format)
                        box = boxes.xyxy[i].cpu().numpy()
                        x1, y1, x2, y2 = box
                        
                        # Get confidence
                        confidence = float(boxes.conf[i].cpu().numpy())
                        
                        # Get class
                        class_id = int(boxes.cls[i].cpu().numpy())
                        
                        # Get class name (assumes 'goat' is in model names)
                        class_name = result.names.get(class_id, 'goat')
                        
                        detections.append({
                            'bbox': {
                                'x': float(x1),
                                'y': float(y1),
                                'width': float(x2 - x1),
                                'height': float(y2 - y1)
                            },
                            'confidence': confidence,
                            'class': class_id,
                            'label': class_name
                        })
            
            return {
                'count': len(detections),
                'detections': detections,
                'confidence': max([d['confidence'] for d in detections]) if detections else 0.0
            }
            
        except Exception as e:
            logger.error(f"Detection failed: {e}")
            return {
                'count': 0,
                'detections': [],
                'confidence': 0.0,
                'error': str(e)
            }


class RFDETRDetector(BaseDetector):
    """RF-DETR object detector backed by an uploaded training checkpoint.

    The selected Nano/Small/etc. variant supplies the architecture for training
    checkpoints that do not record a model name. Checkpoints are loaded in
    RF-DETR's safe mode; unsafe pickle fallback is deliberately never enabled
    for uploaded files.
    """

    def __init__(self, model_path: str, confidence_threshold: float = 0.5,
                 use_gpu: bool = False, **_unused):
        super().__init__(model_path, confidence_threshold)

        try:
            import torch
            from rfdetr import (
                RFDETR, RFDETRNano, RFDETRSmall, RFDETRMedium, RFDETRLarge,
            )
        except ImportError as exc:
            raise ImportError(
                "RF-DETR support is not installed. Install project requirements "
                "with: pip install rfdetr"
            ) from exc

        device = 'cuda' if use_gpu and torch.cuda.is_available() else 'cpu'
        if use_gpu and device == 'cpu':
            logger.warning("GPU requested for RF-DETR but CUDA is unavailable; using CPU")

        metadata = _unused.get('metadata') or {}
        rfdetr_metadata = metadata.get('rfdetr', metadata)
        variant = str(rfdetr_metadata.get('variant', 'nano')).lower()
        variants = {
            'nano': RFDETRNano,
            'small': RFDETRSmall,
            'medium': RFDETRMedium,
            'large': RFDETRLarge,
        }

        try:
            if variant == 'auto':
                self.model = RFDETR.from_checkpoint(
                    str(model_path), device=device, trust_checkpoint=False,
                )
            else:
                model_class = variants.get(variant)
                if model_class is None:
                    raise ValueError(f"Unsupported RF-DETR variant: {variant}")
                self.model = model_class(
                    pretrain_weights=str(model_path),
                    device=device,
                    trust_checkpoint=False,
                )
        except Exception as exc:
            raise ValueError(
                f"Unable to load this RF-DETR {variant} checkpoint safely. Check "
                "that the selected variant matches the downloaded weights and "
                "upload an original .pth, .pt, or .ckpt checkpoint."
            ) from exc

        self.device = device
        self.class_names = list(getattr(self.model, 'class_names', []) or [])
        logger.info("RF-DETR model loaded: %s on %s", model_path, device)

    def detect(self, image: np.ndarray) -> Dict:
        """Run RF-DETR inference and normalize results for the existing pipeline."""
        if image is None or not isinstance(image, np.ndarray):
            raise ValueError("RF-DETR expects an OpenCV image array.")

        try:
            from PIL import Image

            # OpenCV frames are BGR; RF-DETR's PIL input path expects RGB.
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            predictions = self.model.predict(
                Image.fromarray(rgb), threshold=self.confidence_threshold
            )

            detections = []
            xyxy_values = getattr(predictions, 'xyxy', [])
            confidence_values = getattr(predictions, 'confidence', [])
            class_values = getattr(predictions, 'class_id', [])

            for box, confidence, class_id in zip(
                    xyxy_values, confidence_values, class_values):
                x1, y1, x2, y2 = [float(value) for value in box]
                class_id = int(class_id)
                label = (self.class_names[class_id]
                         if 0 <= class_id < len(self.class_names)
                         else str(class_id))
                detections.append({
                    'bbox': {
                        'x': x1,
                        'y': y1,
                        'width': max(0.0, x2 - x1),
                        'height': max(0.0, y2 - y1),
                    },
                    'confidence': float(confidence),
                    'class': class_id,
                    'label': label,
                })

            return {
                'count': len(detections),
                'detections': detections,
                'confidence': max(
                    (item['confidence'] for item in detections), default=0.0
                ),
            }
        except Exception as exc:
            logger.error("RF-DETR detection failed: %s", exc)
            return {
                'count': 0,
                'detections': [],
                'confidence': 0.0,
                'error': str(exc),
            }


class RoboflowInferenceDetector(BaseDetector):
    """
    Roboflow Inference (self-hosted) detector.

    Expects a local inference server (default: http://localhost:9001).
    Uses API key + model ID from environment or metadata.
    """

    def __init__(
        self,
        model_path: str,
        confidence_threshold: float = 0.5,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        model_id: Optional[str] = None,
        overlap: Optional[float] = None,
        timeout: Optional[int] = None,
        metadata: Optional[Dict] = None,
        **_unused,
    ):
        super().__init__(model_path, confidence_threshold)

        metadata = metadata or {}
        roboflow_meta = metadata.get('roboflow', metadata) if isinstance(metadata, dict) else {}

        def _get_env_value(meta: Dict, meta_key: str, fallback_key: str) -> Optional[str]:
            env_key = meta.get(meta_key) if isinstance(meta, dict) else None
            if env_key:
                return os.getenv(env_key)
            return os.getenv(fallback_key)

        self.endpoint = (endpoint or roboflow_meta.get('endpoint') or os.getenv(
            'ROBOFLOW_INFERENCE_URL', 'http://localhost:9001'
        )).rstrip('/')

        self.api_key = api_key or roboflow_meta.get('api_key') or _get_env_value(
            roboflow_meta, 'api_key_env', 'ROBOFLOW_API_KEY'
        )
        self.model_id = model_id or roboflow_meta.get('model_id') or roboflow_meta.get('model') or _get_env_value(
            roboflow_meta, 'model_env', 'ROBOFLOW_MODEL_ID'
        )

        self.overlap = overlap if overlap is not None else roboflow_meta.get('overlap', 0.3)
        self.timeout = timeout if timeout is not None else roboflow_meta.get('timeout', 15)

        if not self.api_key:
            raise ValueError("Missing Roboflow API key. Set ROBOFLOW_API_KEY or metadata.")
        if not self.model_id:
            raise ValueError("Missing Roboflow model ID. Set ROBOFLOW_MODEL_ID or metadata.")

        self.infer_url = self.endpoint if self.endpoint.endswith('/infer') else f"{self.endpoint}/infer"

        logger.info("✅ Roboflow Inference configured")
        logger.info(f"   Endpoint: {self.infer_url}")
        logger.info(f"   Model: {self.model_id}")
        logger.info(f"   Confidence threshold: {confidence_threshold}")

    def detect(self, image: np.ndarray) -> Dict:
        """Run Roboflow Inference on image."""
        if not CV2_AVAILABLE:
            raise RuntimeError("OpenCV is required for Roboflow inference.")

        try:
            ok, encoded = cv2.imencode('.jpg', image)
            if not ok:
                raise ValueError("Failed to encode image for Roboflow inference.")

            params = {
                'api_key': self.api_key,
                'model': self.model_id,
                'confidence': self.confidence_threshold,
                'overlap': self.overlap,
            }

            def _post_with_field(field_name: str):
                return requests.post(
                    self.infer_url,
                    params=params,
                    files={
                        field_name: ('frame.jpg', encoded.tobytes(), 'image/jpeg')
                    },
                    timeout=self.timeout
                )

            response = _post_with_field('file')
            if response.status_code == 405:
                response = _post_with_field('image')

            response.raise_for_status()

            data = response.json() or {}
            predictions = data.get('predictions', [])

            detections = []
            for pred in predictions:
                x_center = pred.get('x')
                y_center = pred.get('y')
                width = pred.get('width')
                height = pred.get('height')
                if x_center is None or y_center is None or width is None or height is None:
                    continue

                x = float(x_center) - float(width) / 2.0
                y = float(y_center) - float(height) / 2.0

                detections.append({
                    'bbox': {
                        'x': float(max(0.0, x)),
                        'y': float(max(0.0, y)),
                        'width': float(width),
                        'height': float(height)
                    },
                    'confidence': float(pred.get('confidence', 0.0)),
                    'class': int(pred.get('class_id', 0)),
                    'label': pred.get('class', 'goat')
                })

            return {
                'count': len(detections),
                'detections': detections,
                'confidence': max([d['confidence'] for d in detections]) if detections else 0.0
            }

        except Exception as e:
            logger.error(f"Roboflow inference failed: {e}")
            return {
                'count': 0,
                'detections': [],
                'confidence': 0.0,
                'error': str(e)
            }


class RoboflowHostedDetector(BaseDetector):
    """
    Roboflow Hosted API detector (cloud).

    Uses the Roboflow hosted endpoint:
    https://detect.roboflow.com/<model_id>
    """

    def __init__(
        self,
        model_path: str,
        confidence_threshold: float = 0.5,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        model_id: Optional[str] = None,
        overlap: Optional[float] = None,
        timeout: Optional[int] = None,
        metadata: Optional[Dict] = None,
        **_unused,
    ):
        super().__init__(model_path, confidence_threshold)

        metadata = metadata or {}
        roboflow_meta = metadata.get('roboflow', metadata) if isinstance(metadata, dict) else {}

        def _get_env_value(meta: Dict, meta_key: str, fallback_key: str) -> Optional[str]:
            env_key = meta.get(meta_key) if isinstance(meta, dict) else None
            if env_key:
                return os.getenv(env_key)
            return os.getenv(fallback_key)

        self.endpoint = (endpoint or roboflow_meta.get('endpoint') or os.getenv(
            'ROBOFLOW_HOSTED_URL', 'https://detect.roboflow.com'
        )).rstrip('/')

        self.api_key = api_key or roboflow_meta.get('api_key') or _get_env_value(
            roboflow_meta, 'api_key_env', 'ROBOFLOW_API_KEY'
        )
        self.model_id = model_id or roboflow_meta.get('model_id') or roboflow_meta.get('model') or _get_env_value(
            roboflow_meta, 'model_env', 'ROBOFLOW_MODEL_ID'
        )

        self.overlap = overlap if overlap is not None else roboflow_meta.get('overlap', 0.3)
        self.timeout = timeout if timeout is not None else roboflow_meta.get('timeout', 15)

        if not self.api_key:
            raise ValueError("Missing Roboflow API key. Set ROBOFLOW_API_KEY or metadata.")
        if not self.model_id:
            raise ValueError("Missing Roboflow model ID. Set ROBOFLOW_MODEL_ID or metadata.")

        self.infer_url = f"{self.endpoint}/{self.model_id.strip('/')}"

        logger.info("✅ Roboflow Hosted API configured")
        logger.info(f"   Endpoint: {self.infer_url}")
        logger.info(f"   Model: {self.model_id}")
        logger.info(f"   Confidence threshold: {confidence_threshold}")

    def detect(self, image: np.ndarray) -> Dict:
        """Run Roboflow Hosted API inference on image."""
        if not CV2_AVAILABLE:
            raise RuntimeError("OpenCV is required for Roboflow inference.")

        try:
            ok, encoded = cv2.imencode('.jpg', image)
            if not ok:
                raise ValueError("Failed to encode image for Roboflow inference.")

            params = {
                'api_key': self.api_key,
                'confidence': self.confidence_threshold,
                'overlap': self.overlap,
            }

            files = {
                'image': ('frame.jpg', encoded.tobytes(), 'image/jpeg')
            }

            response = requests.post(
                self.infer_url,
                params=params,
                files=files,
                timeout=self.timeout
            )
            response.raise_for_status()

            data = response.json() or {}
            predictions = data.get('predictions', [])

            detections = []
            for pred in predictions:
                x_center = pred.get('x')
                y_center = pred.get('y')
                width = pred.get('width')
                height = pred.get('height')
                if x_center is None or y_center is None or width is None or height is None:
                    continue

                x = float(x_center) - float(width) / 2.0
                y = float(y_center) - float(height) / 2.0

                detections.append({
                    'bbox': {
                        'x': float(max(0.0, x)),
                        'y': float(max(0.0, y)),
                        'width': float(width),
                        'height': float(height)
                    },
                    'confidence': float(pred.get('confidence', 0.0)),
                    'class': int(pred.get('class_id', 0)),
                    'label': pred.get('class', 'goat')
                })

            return {
                'count': len(detections),
                'detections': detections,
                'confidence': max([d['confidence'] for d in detections]) if detections else 0.0
            }

        except Exception as e:
            logger.error(f"Roboflow hosted inference failed: {e}")
            return {
                'count': 0,
                'detections': [],
                'confidence': 0.0,
                'error': str(e)
            }


def get_detector(model_type: str, model_path: str, **kwargs) -> BaseDetector:
    """
    Factory function to get appropriate detector.
    
    Args:
        model_type: 'tensorflow', 'pytorch', 'yolov8', or 'rfdetr'
        model_path: Path to model file
        **kwargs: Additional arguments for detector
        
    Returns:
        Detector instance
    """
    model_type = model_type.lower()
    
    if model_type in ['yolov8', 'ultralytics']:
        return YOLOv8Detector(model_path, **kwargs)
    elif model_type in ['rfdetr', 'rf-detr', 'rf_detr']:
        return RFDETRDetector(model_path, **kwargs)
    elif model_type in ['roboflow', 'roboflow-inference', 'roboflow_inference']:
        return RoboflowInferenceDetector(model_path, **kwargs)
    elif model_type in ['roboflow-hosted', 'roboflow_hosted', 'roboflow_api']:
        return RoboflowHostedDetector(model_path, **kwargs)
    elif model_type in ['tensorflow', 'keras', 'yolo']:
        return TensorFlowDetector(model_path, **kwargs)
    elif model_type == 'pytorch':
        return PyTorchDetector(model_path, **kwargs)
    else:
        raise ValueError(f"Unsupported model type: {model_type}")


def draw_detections(image: np.ndarray, detections: List[Dict]) -> np.ndarray:
    """
    Draw bounding boxes on image.
    
    Args:
        image: Original image
        detections: List of detection dicts
        
    Returns:
        Image with drawn boxes
    """
    img_copy = image.copy()
    
    for detection in detections:
        bbox = detection['bbox']
        confidence = detection['confidence']
        
        x = int(bbox['x'])
        y = int(bbox['y'])
        w = int(bbox['width'])
        h = int(bbox['height'])
        
        # Draw rectangle
        cv2.rectangle(img_copy, (x, y), (x + w, y + h), (0, 255, 0), 2)
        
        # Draw label
        label = f"Goat {confidence:.2f}"
        cv2.putText(img_copy, label, (x, y - 10), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
    
    return img_copy


def detect_and_identify_goats(image: np.ndarray, detector, camera,
                               enable_reid: bool = True) -> Dict:
    """
    Run detection and re-identification on an image.

    This is the main pipeline that combines:
    1. YOLOv8 detection (find all goats)
    2. Feature extraction (get embeddings)
    3. Re-identification (match against manually-registered goats)

    Unknown goats are reported as unidentified detections; the pipeline never
    creates goat records (registration is manual only).

    Args:
        image: Input image (BGR format from OpenCV)
        detector: YOLOv8Detector instance
        camera: IPCamera instance
        enable_reid: Enable re-identification (default: True)

    Returns:
        Dict with detection and identification results
    """
    # Step 1: Run YOLOv8 detection
    detection_result = detector.detect(image)
    
    if not enable_reid or detection_result['count'] == 0:
        # Return detection results only
        return {
            'detection_count': detection_result['count'],
            'detections': detection_result['detections'],
            'confidence': detection_result['confidence'],
            'identified_goats': [],
            'new_goats': [],
            'reid_enabled': False
        }
    
    # Step 2: Run re-identification on detected goats
    try:
        from .reid_service import identify_goats_from_frame
        
        reid_results = identify_goats_from_frame(
            image=image,
            detections=detection_result['detections'],
            camera=camera
        )
        
        return {
            'detection_count': detection_result['count'],
            'detections': detection_result['detections'],
            'confidence': detection_result['confidence'],
            'identified_goats': reid_results['identified_goats'],
            'new_goats': reid_results['new_goats'],
            'reid_enabled': True,
            'timestamp': reid_results['timestamp']
        }
        
    except Exception as e:
        logger.error(f"Re-identification failed: {e}")
        # Fall back to detection only
        return {
            'detection_count': detection_result['count'],
            'detections': detection_result['detections'],
            'confidence': detection_result['confidence'],
            'identified_goats': [],
            'new_goats': [],
            'reid_enabled': False,
            'error': str(e)
        }


def draw_identified_goats(image: np.ndarray, results: Dict) -> np.ndarray:
    """
    Draw bounding boxes with goat IDs on image.
    
    Args:
        image: Original image
        results: Results from detect_and_identify_goats()
        
    Returns:
        Image with drawn boxes and goat IDs
    """
    img_copy = image.copy()
    
    # Draw identified goats (green boxes)
    for result in results.get('identified_goats', []):
        bbox = result['bbox']
        goat_id = result['goat_id']
        similarity = result['similarity']
        
        x = int(bbox['x'])
        y = int(bbox['y'])
        w = int(bbox['width'])
        h = int(bbox['height'])
        
        # Green box for identified goats
        cv2.rectangle(img_copy, (x, y), (x + w, y + h), (0, 255, 0), 2)
        
        # Label with goat ID and similarity
        label = f"{goat_id} ({similarity:.2f})"
        cv2.putText(img_copy, label, (x, y - 10), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    
    # Draw new goats (yellow boxes)
    for result in results.get('new_goats', []):
        bbox = result['bbox']
        goat_id = result['goat_id']
        
        x = int(bbox['x'])
        y = int(bbox['y'])
        w = int(bbox['width'])
        h = int(bbox['height'])
        
        # Yellow box for new goats
        cv2.rectangle(img_copy, (x, y), (x + w, y + h), (0, 255, 255), 2)
        
        # Label with "NEW" indicator
        label = f"{goat_id} (NEW)"
        cv2.putText(img_copy, label, (x, y - 10), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
    
    # Add count summary at top
    total_count = len(results.get('identified_goats', [])) + len(results.get('new_goats', []))
    summary = f"Total: {total_count} | Identified: {len(results.get('identified_goats', []))} | New: {len(results.get('new_goats', []))}"
    cv2.putText(img_copy, summary, (10, 30), 
               cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    
    return img_copy
