from __future__ import annotations

import json
import random
from pathlib import Path

import torch
from torch import nn

from .contracts import LABELS
from .dataset import save_jsonl
from .features import fit_normalizer, normalize
from .graph import build_graph_sample
from .model import BaselineNodeClassifier, BottleneckGNN
from app.services.plans.models import PlanGraph, PlanNode

SEED = 20261003


def _node(node_type, cost, rows, actual_rows, loops=1, time=1, index=None):
    return PlanNode(node_id="", node_type=node_type, relation="orders", index_name=index,
                    startup_cost=cost * .1, total_cost=cost, plan_rows=rows,
                    actual_rows=actual_rows, actual_loops=loops, actual_total_time_ms=time)


def synthetic_graph(i: int) -> PlanGraph:
    rng = random.Random(SEED + i)
    kind = i % 5
    if kind == 0:
        root = _node("Seq Scan", rng.uniform(150, 700), 10000, 9000, time=rng.uniform(30, 160))
        root.node_id = "n1"; return PlanGraph("n1", {"n1": root}, [])
    if kind == 1:
        root = _node("Nested Loop", 250, 20, 20, loops=rng.randint(120, 500), time=rng.uniform(30, 120))
        child = _node("Index Scan", 50, 20, 20, time=2, index="orders_customer_idx"); child.node_id="n2"; root.node_id="n1"
        root.children=["n2"]; return PlanGraph("n1", {"n1":root,"n2":child}, [("n1","n2")])
    if kind == 2:
        root = _node("Sort", 180, 1000, 1000, time=rng.uniform(15, 90)); root.node_id="n1"
        child = _node("Index Scan", 70, 1000, 1000, time=4, index="orders_created_idx"); child.node_id="n2"; root.children=["n2"]
        return PlanGraph("n1", {"n1":root,"n2":child}, [("n1","n2")])
    if kind == 3:
        root = _node("Hash Join", 220, 100, 3000, time=rng.uniform(8, 50)); root.node_id="n1"
        child = _node("Seq Scan", 100, 1000, 1000, time=10); child.node_id="n2"; root.children=["n2"]
        return PlanGraph("n1", {"n1":root,"n2":child}, [("n1","n2")])
    root = _node("Index Scan", 80, 1000, 50, time=rng.uniform(2, 8), index="orders_customer_idx"); root.node_id="n1"
    return PlanGraph("n1", {"n1":root}, [])


def make_dataset(count: int = 500):
    return [build_graph_sample(synthetic_graph(i), f"synthetic-{i:04d}") for i in range(count)]


def _tensor(sample, normalizer):
    x = torch.tensor(normalize(sample.node_features, normalizer), dtype=torch.float32)
    edge = torch.tensor(sample.edge_index, dtype=torch.long).t().contiguous() if sample.edge_index else torch.empty((2,0), dtype=torch.long)
    edge_attr = torch.tensor(sample.edge_features, dtype=torch.float32) if sample.edge_features else torch.empty((0,3), dtype=torch.float32)
    y = torch.tensor(sample.node_labels, dtype=torch.long)
    return x, edge, edge_attr, y


def _metrics(model, samples, normalizer):
    model.eval(); pred=[]; truth=[]
    with torch.no_grad():
        for s in samples:
            x,e,ea,y=_tensor(s,normalizer); p=model(x,e,ea).argmax(1); pred.extend(p.tolist()); truth.extend(y.tolist())
    correct=sum(a==b for a,b in zip(pred,truth)); n=max(len(truth),1)
    f1s=[]
    for c in range(len(LABELS)):
        tp=sum(a==c and b==c for a,b in zip(pred,truth)); fp=sum(a==c and b!=c for a,b in zip(pred,truth)); fn=sum(a!=c and b==c for a,b in zip(pred,truth))
        precision=tp/max(tp+fp,1); recall=tp/max(tp+fn,1); f1=2*precision*recall/max(precision+recall,1e-12); f1s.append(f1)
    return {"accuracy": correct/n, "macro_f1": sum(f1s)/len(f1s), "support": n}


def train_and_evaluate(out_dir: Path, count: int = 250, epochs: int = 20):
    torch.manual_seed(SEED); random.seed(SEED)
    samples=make_dataset(count); split=int(count*.8); train_samples=samples[:split]; val_samples=samples[split:]
    normalizer=fit_normalizer(train_samples)
    results={"seed":SEED,"dataset_size":count,"train_size":len(train_samples),"validation_size":len(val_samples),"labels":list(LABELS),"feature_count":len(samples[0].node_features[0]),"pyg_available":False}
    out_dir.mkdir(parents=True,exist_ok=True); save_jsonl(samples, out_dir/"synthetic_plans.jsonl")
    models={"baseline":BaselineNodeClassifier(len(samples[0].node_features[0]),len(LABELS)),"gnn":BottleneckGNN(len(samples[0].node_features[0]),32,len(LABELS))}
    for name,model in models.items():
        opt=torch.optim.Adam(model.parameters(),lr=0.01,weight_decay=1e-4); loss_fn=nn.CrossEntropyLoss()
        for _ in range(epochs):
            model.train(); total=0
            for s in train_samples:
                x,e,ea,y=_tensor(s,normalizer); opt.zero_grad(); loss=loss_fn(model(x,e,ea),y); loss.backward(); opt.step(); total+=loss.item()
        results[name]=_metrics(model,val_samples,normalizer)
        torch.save(model.state_dict(), out_dir/f"{name}.pt")
        results["pyg_available"] = results["pyg_available"] or getattr(model,"uses_pyg",False)
    (out_dir/"normalizer.json").write_text(json.dumps(normalizer,indent=2),encoding="utf-8")
    (out_dir/"metrics.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
    return results
