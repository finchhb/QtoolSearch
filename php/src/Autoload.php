<?php
declare(strict_types=1);

spl_autoload_register(static function (string $class): void {
    $prefix = 'Qtool\\';
    if (!str_starts_with($class, $prefix)) {
        return;
    }
    $rel = substr($class, strlen($prefix));
    $file = __DIR__ . '/' . str_replace('\\', '/', $rel) . '.php';
    if (is_file($file)) {
        require $file;
    }
});