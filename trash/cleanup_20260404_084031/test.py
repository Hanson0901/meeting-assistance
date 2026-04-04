#To make sure your python environment is match or requirements
import torch
import transformers
print(f"PyTorch版本: {torch.__version__}")
print(f"Transformers版本: {transformers.__version__}")
print(f"CUDA可用: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"CUDA版本: {torch.version.cuda}")
    print(f"GPU數量: {torch.cuda.device_count()}")
print(torch.cuda.get_device_capability())