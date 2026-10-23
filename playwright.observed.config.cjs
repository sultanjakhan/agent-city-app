const {defineConfig}=require('@playwright/test');
module.exports=defineConfig({testDir:'./tests',testMatch:'observed-ui.spec.cjs',workers:1,retries:0,
 use:{browserName:'chromium',headless:true,trace:'off'},outputDir:'test-results/observed-synthetic'});
