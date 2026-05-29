"""
SkyOptimizer AI — PyTorch Model Eğitimi
RTX 4070 (CUDA) üzerinde uçuş yakıt/süre tahmini için
Derin Sinir Ağı (DNN) eğitimi.

Kullanım:
    python ml/train_model.py

Gereksinimler:
    pip install torch pandas scikit-learn
"""

import os
import sys
import time
import pandas as pd
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, MinMaxScaler
import pickle

# ─── Sabitler ─────────────────────────────────────────────────────
ML_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(ML_DIR, "flight_data.csv")
MODEL_FILE = os.path.join(ML_DIR, "model.pt")
SCALER_FILE = os.path.join(ML_DIR, "scaler.pkl")

FEATURE_COLS = [
    "distance_nm",
    "wind_speed_kts",
    "wind_direction_deg",
    "aircraft_heading_deg",
    "altitude_ft",
    "headwind_kts",
    "crosswind_kts",
]

TARGET_COLS = [
    "fuel_kg",
    "time_min",
    "co2_kg",
]


# ─── Model Mimarisi ──────────────────────────────────────────────
class FlightCostPredictor(nn.Module):
    """
    4 katmanlı DNN — uçuş parametrelerinden yakıt/süre/CO₂ tahmini.
    """
    def __init__(self, input_dim: int = 7, output_dim: int = 3):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 512),
            nn.LeakyReLU(0.01),
            nn.BatchNorm1d(512),

            nn.Linear(512, 256),
            nn.LeakyReLU(0.01),
            nn.BatchNorm1d(256),

            nn.Linear(256, 128),
            nn.LeakyReLU(0.01),
            nn.BatchNorm1d(128),

            nn.Linear(128, 64),
            nn.LeakyReLU(0.01),

            nn.Linear(64, output_dim),
        )

    def forward(self, x):
        return self.net(x)


# ─── Eğitim ──────────────────────────────────────────────────────
def train():
    # 1. Veri yükle
    if not os.path.exists(DATA_FILE):
        print("[HATA] Eğitim verisi bulunamadı! Önce data_collector.py çalıştırın.")
        print(f"       Beklenen dosya: {DATA_FILE}")
        sys.exit(1)

    print("=" * 60)
    print("  SkyOptimizer AI — Model Eğitimi")
    print("=" * 60)

    df = pd.read_csv(DATA_FILE)
    print(f"\n[VERİ] {len(df):,} satır yüklendi")
    print(f"[VERİ] Özellikler: {FEATURE_COLS}")
    print(f"[VERİ] Hedefler:   {TARGET_COLS}")

    # 2. Cihaz seçimi
    if torch.cuda.is_available():
        device = torch.device("cuda")
        gpu_name = torch.cuda.get_device_name(0)
        vram = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        print(f"\n[GPU]  {gpu_name}  ({vram:.1f} GB VRAM)")
    else:
        device = torch.device("cpu")
        print("\n[CPU]  CUDA bulunamadı, CPU ile eğitim yapılacak")

    # 3. Feature / Label ayırma
    X = df[FEATURE_COLS].values.astype(np.float32)
    y = df[TARGET_COLS].values.astype(np.float32)

    # 4. Normalize et
    # Feature'lar: StandardScaler (zero-mean, unit-var)
    # Hedefler: MinMaxScaler (0-1) — donusum yok, saf degerler
    scaler_X = StandardScaler()
    scaler_y = MinMaxScaler(feature_range=(0, 1))

    X = scaler_X.fit_transform(X)
    y = scaler_y.fit_transform(y)

    # Scaler'lari kaydet
    with open(SCALER_FILE, "wb") as f:
        pickle.dump({"X": scaler_X, "y": scaler_y, "target_transform": None}, f)
    print(f"[SCALER] Kaydedildi: {SCALER_FILE} (MinMaxScaler, donusum yok)")

    # 5. Train/test split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.15, random_state=42
    )
    print(f"\n[SPLIT] Train: {len(X_train):,}  |  Test: {len(X_test):,}")

    # 6. DataLoader
    train_ds = TensorDataset(
        torch.tensor(X_train, dtype=torch.float32),
        torch.tensor(y_train, dtype=torch.float32),
    )
    test_ds = TensorDataset(
        torch.tensor(X_test, dtype=torch.float32),
        torch.tensor(y_test, dtype=torch.float32),
    )
    train_loader = DataLoader(train_ds, batch_size=512, shuffle=True)
    test_loader = DataLoader(test_ds, batch_size=1024)

    # 7. Model, loss, optimizer
    model = FlightCostPredictor(
        input_dim=len(FEATURE_COLS),
        output_dim=len(TARGET_COLS),
    ).to(device)

    criterion = nn.MSELoss()  # Saf MSE — temiz veri icin en iyi
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-5)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=200, eta_min=1e-6
    )

    param_count = sum(p.numel() for p in model.parameters())
    print(f"\n[MODEL] FlightCostPredictor — {param_count:,} parametre")
    print(f"[MODEL] Loss: MSELoss | Optimizer: AdamW | Scheduler: CosineAnnealing")
    print(f"[MODEL] Cihaz: {device}")

    # 8. Egitim dongusu
    epochs = 200
    best_loss = float("inf")
    patience_counter = 0
    max_patience = 30

    print(f"\n{'Epoch':>6}  {'Train Loss':>12}  {'Test Loss':>12}  {'LR':>10}  {'Süre':>8}")
    print("-" * 56)

    t_start = time.time()

    for epoch in range(1, epochs + 1):
        t_ep = time.time()

        # Train
        model.train()
        train_loss = 0.0
        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)
            pred = model(xb)
            loss = criterion(pred, yb)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * xb.size(0)
        train_loss /= len(train_ds)

        # Eval
        model.eval()
        test_loss = 0.0
        with torch.no_grad():
            for xb, yb in test_loader:
                xb, yb = xb.to(device), yb.to(device)
                pred = model(xb)
                test_loss += criterion(pred, yb).item() * xb.size(0)
        test_loss /= len(test_ds)

        scheduler.step()  # CosineAnnealing: argumansiz
        lr = optimizer.param_groups[0]["lr"]
        elapsed = time.time() - t_ep

        if epoch % 5 == 0 or epoch == 1:
            print(f"{epoch:>6}  {train_loss:>12.6f}  {test_loss:>12.6f}  {lr:>10.2e}  {elapsed:>7.2f}s")

        # Early stopping
        if test_loss < best_loss:
            best_loss = test_loss
            patience_counter = 0
            torch.save({
                "model_state": model.state_dict(),
                "input_dim": len(FEATURE_COLS),
                "output_dim": len(TARGET_COLS),
                "feature_cols": FEATURE_COLS,
                "target_cols": TARGET_COLS,
                "best_loss": best_loss,
            }, MODEL_FILE)
        else:
            patience_counter += 1
            if patience_counter >= max_patience:
                print(f"\n[STOP] Early stopping — {max_patience} epoch iyileşme yok")
                break

    total_time = time.time() - t_start
    print(f"\n{'='*56}")
    print(f"  Eğitim tamamlandı!")
    print(f"  Toplam süre : {total_time:.1f}s")
    print(f"  En iyi loss : {best_loss:.6f}")
    print(f"  Model dosyası: {MODEL_FILE}")
    print(f"{'='*56}")

    # 9. Son doğrulama: gerçek değerle karşılaştır
    _evaluate(model, device, X_test, y_test, scaler_y)


def _evaluate(model, device, X_test, y_test, scaler_y):
    """Test setinde örnek tahminler göster."""
    model.eval()
    with torch.no_grad():
        x_t = torch.tensor(X_test[:5], dtype=torch.float32).to(device)
        pred = model(x_t).cpu().numpy()

    # Ters normalize
    pred_real = scaler_y.inverse_transform(pred)
    true_real = scaler_y.inverse_transform(y_test[:5])

    print(f"\n{'-'*60}")
    print("  Ornek Tahminler (ilk 5 satir)")
    print(f"{'-'*60}")
    print(f"  {'':>4}  {'Fuel(kg)':>12}  {'Time(min)':>12}  {'CO2(kg)':>12}")
    for i in range(5):
        print(f"  Gerçek  {true_real[i,0]:>10.1f}  {true_real[i,1]:>12.1f}  {true_real[i,2]:>12.1f}")
        print(f"  Tahmin  {pred_real[i,0]:>10.1f}  {pred_real[i,1]:>12.1f}  {pred_real[i,2]:>12.1f}")
        print()


if __name__ == "__main__":
    train()
