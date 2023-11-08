from google.cloud import storage
from datetime import datetime
import pytz
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
import joblib
import json
import os
import logging
import gcsfs


def load_data(gcs_train_data_path):
    # Initialize GCSFileSystem object
    fs = gcsfs.GCSFileSystem()
    
    with fs.open(gcs_train_data_path) as f:
        df = pd.read_csv(f)

    column_names = [
        'Date', 'Time', 'CO(GT)', 'PT08.S1(CO)', 'NMHC(GT)', 'C6H6(GT)', 'PT08.S2(NMHC)', 
        'NOx(GT)', 'PT08.S3(NOx)', 'NO2(GT)', 'PT08.S4(NO2)', 'PT08.S5(O3)', 'T', 'RH', 'AH'
    ]
    # Ensure the columns are named correctly
    df.columns = column_names
    
    return df

def normalize_data(data, stats):
    normalized_data = {}
    for column in data.columns:
        mean = stats["mean"][column]
        std = stats["std"][column]
        
        normalized_data[column] = [(value - mean) / std for value in data[column]]
    
    # Convert normalized_data dictionary back to a DataFrame
    normalized_df = pd.DataFrame(normalized_data, index=data.index)
    return normalized_df

def data_transform(df):
    
    df['Datetime'] = pd.to_datetime(df['Date'] + ' ' + df['Time'])
    df.set_index('Datetime', inplace=True)
    df.drop(columns=['Date', 'Time'], inplace=True)

    # Splitting the data into training and testing sets (80% training, 20% testing)
    train, test = train_test_split(df, test_size=0.2, shuffle=False)

    # Separating features and target variable
    X_train = train.drop(columns=['CO(GT)'])
    y_train = train['CO(GT)']

    X_test = test.drop(columns=['CO(GT)'])
    y_test = test['CO(GT)']

     # Get the json from GCS
    client = storage.Client()
    bucket_name = 'mlops-data-ie7374' # Change this to your bucket name
    blob_path = 'scaler/normalization_stats.json' # Change this to your blob path where the data is stored
    bucket = client.get_bucket(bucket_name)
    blob = bucket.blob(blob_path)

    # Download the json as a string
    data = blob.download_as_string()
    stats = json.loads(data)

    # Normalize the data using the statistics from the training set
    X_train_scaled = normalize_data(X_train, stats)
    y_train_scaled = (y_train - stats["mean"]['CO(GT)']) / stats["std"]['CO(GT)']
    
    return X_train_scaled, X_test, y_train_scaled, y_test



def train_model(X_train, y_train):
    model = RandomForestRegressor(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)
    return model


gcs_train_data_path = "gs://mlops-data-ie7374/data/train/train_data.csv" # Change this to your train data path in GCS
df = load_data(gcs_train_data_path)
X_train, X_test, y_train, y_test = data_transform(df)
model = train_model(X_train, y_train)

local_model_path = "model.pkl"
joblib.dump(model, local_model_path)



edt = pytz.timezone('US/Eastern')

# Get the current time in EDT
current_time_edt = datetime.now(edt)

version = current_time_edt.strftime('%d-%m-%Y-%H%M%S')

MODEL_DIR  = os.getenv("AIP_MODEL_DIR")
gcs_model_path = os.path.join(MODEL_DIR, "model_" + str(version) + ".pkl")

storage_client = storage.Client()
bucket_name, blob_path = gcs_model_path.split("gs://")[1].split("/", 1)
bucket = storage_client.bucket(bucket_name)
blob_model = bucket.blob(blob_path)
blob_model.upload_from_filename(local_model_path)

model_gcs_path = "gs://mlops-data-ie7374/model/" + "model_" + str(version) + ".pkl"

# Use gcsfs to open a GCS file for writing
with gcsfs.GCSFileSystem().open(model_gcs_path, 'wb') as f:
    joblib.dump(model, f)





