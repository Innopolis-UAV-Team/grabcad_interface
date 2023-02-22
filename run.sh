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

python3 /grabcad/pygc.py clone --url "${url}" --email "${email}" --pass "${password}" --dont_save_creds true
