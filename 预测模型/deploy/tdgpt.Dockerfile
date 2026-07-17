FROM tdengine/tdgpt:3.4.1.9

USER root

COPY 模型2/models /opt/coretemp/informer/models
COPY 模型2/utils /opt/coretemp/informer/utils
COPY deploy/model-service/app/informer.py /opt/coretemp/runtime.py
COPY deploy/tdgpt/core_temperature_forecast.py \
  /usr/local/taos/taosanode/lib/taosanalytics/algo/fc/core_temperature_forecast.py

ENV PYTHONPATH=/opt/coretemp:/opt/coretemp/informer

# tdengine/tdgpt already ships with PyTorch. Keep its pinned environment and
# install no second torch build here.
EXPOSE 6035

