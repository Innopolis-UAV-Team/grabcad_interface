#!/bin/bash

while getopts e:p:u: flag
do
    case "${flag}" in
        e) email=${OPTARG};;
        p) password=${OPTARG};;
        u) url=${OPTARG};;
        *)
    esac
done

cd /grabcad_repo || return

python3 /grabcad/pygc.py init --email "${email}" --pass "${password}" --url "${url}" --dont_save_creds true
python3 /grabcad/pygc.py pull --email "${email}" --pass "${password}" --dont_save_creds true
