<?php
$seg='CNMG120408 x5';
$q=[];
$has=preg_match('/(?:(\d+)\s*(?:шт\.?|штук|уп\.?|pcs?)\b|[xх*]\s*(\d+)\s*$)/iu',$seg,$q,PREG_OFFSET_CAPTURE|PREG_UNMATCHED_AS_NULL);
var_export($has); echo "\n"; var_export($q); echo "\n";
