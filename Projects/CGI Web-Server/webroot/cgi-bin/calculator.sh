#!/bin/bash

num1=$1
num2=$2
operator=$3

result=0

if [ "$operator" == "+" ]; then
    result=$((num1 + num2))
elif [ "$operator" == "-" ]; then
    result=$((num1 - num2))
elif [ "$operator" == "*" ]; then
    result=$((num1 * num2))
elif [ "$operator" == "/" ]; then
    result=$(echo "scale=2; $num1 / $num2" | bc)
fi

echo "<p>The result is: $result</p>"
