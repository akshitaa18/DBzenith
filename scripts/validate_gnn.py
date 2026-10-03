from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services.gnn.dataset import load_jsonl
from app.services.gnn.features import fit_normalizer
from app.services.gnn.model import BottleneckGNN
from app.services.gnn.train import _metrics, _tensor
import json
import torch

if __name__ == "__main__":
    root=Path(__file__).resolve().parents[1]/"ai/gnn/models/v0.7.0"
    samples=load_jsonl(root/"synthetic_plans.jsonl")
    split=int(len(samples)*.8); train,val=samples[:split],samples[split:]
    norm=json.loads((root/"normalizer.json").read_text())
    model=BottleneckGNN(21,32,5); model.load_state_dict(torch.load(root/"gnn.pt",map_location="cpu"))
    print(json.dumps(_metrics(model,val,norm),indent=2))
