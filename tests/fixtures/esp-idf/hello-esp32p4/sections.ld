/* Automatically generated file; DO NOT EDIT */
/* Espressif IoT Development Framework Linker Script */
/* Generated from: /work/hello-esp32p4/build/esp-idf/esp_system/ld/sections.ld.in */

/*
 * SPDX-FileCopyrightText: 2022 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: Apache-2.0
 */
/* Default entry point */
ENTRY(call_start_cpu0);
SECTIONS
{
/*
 * Automatically generated file. DO NOT EDIT.
 * Espressif IoT Development Framework (ESP-IDF) 6.0.3 Configuration Header
 */
       
/* List of deprecated options */
/*
 * SPDX-FileCopyrightText: 2021-2024 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: Apache-2.0
 */
/* CPU instruction prefetch padding size for flash mmap scenario */
/*
 * PMP region granularity size
 * Software may determine the PMP granularity by writing zero to pmp0cfg, then writing all ones
 * to pmpaddr0, then reading back pmpaddr0. If G is the index of the least-significant bit set,
 * the PMP granularity is 2^G+2 bytes.
 */
/* CPU instruction prefetch padding size for memory protection scenario */
/* Memory alignment size for PMS */
    /* rtc timer data (s_rtc_timer_retain_mem, see esp_clk.c files). For rtc_timer_data_in_rtc_mem section. */
  /**
   * RTC fast memory holds RTC wake stub code,
   * including from any source file named rtc_wake_stub*.c
   */
  .rtc.text :
  {
    /**
     * Align the start of RTC code region as per PMP granularity.
     * This ensures we do not overwrite the permissions for the previous
     * region (ULP mem/RTC reserved) regardless of their end alignment.
     */
    . = ALIGN(128);
    _rtc_fast_start = ABSOLUTE(.);
    _rtc_text_start = ABSOLUTE(.);
    HIDDEN(_rtc_code_start = .);
    *(.rtc.entry.text)
    
 *(.rtc.literal .rtc.text .rtc.text.*)
 mutable[rtc_text]
    *rtc_wake_stub*.*(.text .text.*)
    *(.rtc_text_end_test)
    /* Align the end of RTC code region as per PMP granularity */
    . = ALIGN(128);
    HIDDEN(_rtc_code_end = .);
    /* Padding for possible CPU prefetch + 4B alignment for PMS split lines. */
    . = ((_rtc_code_end - _rtc_code_start) == 0) ?
        ALIGN(0) : 0 + ALIGN(4);
    _rtc_text_end = ABSOLUTE(.);
  } > rtc_text_seg
  /**
   * This section is located in RTC FAST Memory area.
   * It holds data marked with RTC_FAST_ATTR attribute.
   * See the file "esp_attr.h" for more information.
   */
  .rtc.force_fast :
  {
    
 . = ALIGN(4); 
 _rtc_force_fast_start = ABSOLUTE(.);
    
 mutable[rtc_force_fast]
    *(.rtc.force_fast .rtc.force_fast.*)
    
 . = ALIGN(4); 
 _rtc_force_fast_end = ABSOLUTE(.);
  } > rtc_force_fast_seg
  /**
   * RTC data section holds RTC wake stub data/rodata, including from
   * any source file named rtc_wake_stub*.c and the data marked with
   * RTC_DATA_ATTR, RTC_RODATA_ATTR attributes.
   */
  .rtc.data :
  {
    _rtc_data_start = ABSOLUTE(.);
    
 *(.rtc.data .rtc.data.*)
 *(.rtc.rodata .rtc.rodata.*)
 mutable[rtc_data]
    *rtc_wake_stub*.*(.data .rodata .data.* .rodata.* .srodata.*)
    _rtc_data_end = ABSOLUTE(.);
  } > rtc_data_seg
  /* RTC bss, from any source file named rtc_wake_stub*.c */
  .rtc.bss (NOLOAD) :
  {
    _rtc_bss_start = ABSOLUTE(.);
    *rtc_wake_stub*.*(.bss .bss.* .sbss .sbss.*)
    *rtc_wake_stub*.*(COMMON)
    
 *(.rtc.bss)
 mutable[rtc_bss]
    _rtc_bss_end = ABSOLUTE(.);
  } > rtc_data_seg
  /**
   * This section holds data that should not be initialized at power up
   * and will be retained during deep sleep.
   * User data marked with RTC_NOINIT_ATTR will be placed into this section.
   * See the file "esp_attr.h" for more information.
   */
  .rtc_noinit (NOLOAD) :
  {
    
 . = ALIGN(4); 
 _rtc_noinit_start = ABSOLUTE(.);
    
 mutable[rtc_noinit]
    *(.rtc_noinit .rtc_noinit.*)
    
 . = ALIGN(4); 
 _rtc_noinit_end = ABSOLUTE(.);
  } > rtc_data_seg
  /**
   * This section is located in RTC SLOW Memory area.
   * It holds data marked with RTC_SLOW_ATTR attribute.
   * See the file "esp_attr.h" for more information.
   */
  .rtc.force_slow :
  {
    
 . = ALIGN(4); 
 _rtc_force_slow_start = ABSOLUTE(.);
    *(.rtc.force_slow .rtc.force_slow.*)
    
 . = ALIGN(4); 
 _rtc_force_slow_end = ABSOLUTE(.);
  } > rtc_force_slow_seg
  /**
   * This section holds RTC data that should have fixed addresses.
   * The data are not initialized at power-up and are retained during deep sleep.
   */
  .rtc_reserved (NOLOAD) :
  {
    
 . = ALIGN(4); 
 _rtc_reserved_start = ABSOLUTE(.);
    /**
     * IMPORTANT: Existing data must not be moved.
     * Data have adhered to the beginning or ending of the segment
     * (depending on chip) and code relies on it.
     */
    KEEP(*(.bootloader_data_rtc_mem .bootloader_data_rtc_mem.*))
    *(.rtc_timer_data_in_rtc_mem .rtc_timer_data_in_rtc_mem.*)
    /**
     * Put new data after this line
     * vvvvvvvvvvvvvvvvvvvvvvvvvvvv
     */
    _rtc_reserved_end = ABSOLUTE(.);
  } > rtc_reserved_seg
  _rtc_ulp_memory_start = _rtc_reserved_start + LENGTH(rtc_reserved_seg);
  _rtc_reserved_length = _rtc_reserved_end - _rtc_reserved_start;
  ASSERT((_rtc_reserved_length <= LENGTH(rtc_reserved_seg)),
          "RTC reserved segment data does not fit.")
  /* Get size of rtc slow data based on rtc_data_seg alias */
  _rtc_slow_length = (ORIGIN(rtc_slow_seg) == ORIGIN(rtc_data_seg))
                        ? (_rtc_force_slow_end - _rtc_data_start)
                        : (_rtc_force_slow_end - _rtc_force_slow_start);
  _rtc_fast_length = (ORIGIN(rtc_slow_seg) == ORIGIN(rtc_data_seg))
                        ? (_rtc_force_fast_end - _rtc_fast_start)
                        : (_rtc_noinit_end - _rtc_fast_start);
  ASSERT((_rtc_slow_length <= LENGTH(rtc_slow_seg)),
          "RTC_SLOW segment data does not fit.")
  ASSERT((_rtc_fast_length <= LENGTH(rtc_data_seg)),
          "RTC_FAST segment data does not fit.")
/*
 * SPDX-FileCopyrightText: 2021-2024 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: Apache-2.0
 */
/* CPU instruction prefetch padding size for flash mmap scenario */
/*
 * PMP region granularity size
 * Software may determine the PMP granularity by writing zero to pmp0cfg, then writing all ones
 * to pmpaddr0, then reading back pmpaddr0. If G is the index of the least-significant bit set,
 * the PMP granularity is 2^G+2 bytes.
 */
/* CPU instruction prefetch padding size for memory protection scenario */
/* Memory alignment size for PMS */
    /* rtc timer data (s_rtc_timer_retain_mem, see esp_clk.c files). For rtc_timer_data_in_rtc_mem section. */
  .spm.text :
  {
    /* Code marked as running out of spm */
    _spm_text_start = ABSOLUTE(.);
    
 *(.spm.text .spm.text.*)
 mutable[spm_text]
    _spm_text_end = ABSOLUTE(.);
  } > spm_idram_seg
  .spm.data :
  {
    _spm_data_start = ABSOLUTE(.);
    
 *(.spm.data .spm.data.*)
 mutable[spm_data]
    _spm_data_end = ABSOLUTE(.);
  } > spm_idram_seg
/*
 * SPDX-FileCopyrightText: 2021-2024 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: Apache-2.0
 */
/* CPU instruction prefetch padding size for flash mmap scenario */
/*
 * PMP region granularity size
 * Software may determine the PMP granularity by writing zero to pmp0cfg, then writing all ones
 * to pmpaddr0, then reading back pmpaddr0. If G is the index of the least-significant bit set,
 * the PMP granularity is 2^G+2 bytes.
 */
/* CPU instruction prefetch padding size for memory protection scenario */
/* Memory alignment size for PMS */
    /* rtc timer data (s_rtc_timer_retain_mem, see esp_clk.c files). For rtc_timer_data_in_rtc_mem section. */
  .iram0.text :
  {
    _iram_start = ABSOLUTE(.);
    /* Vectors go to start of IRAM */
    ASSERT(ABSOLUTE(.) % ALIGN_VECTOR_TABLE == 0, "vector address must be ALIGN_VECTOR_TABLE byte aligned");
    _vector_table_start = ABSOLUTE(.);
    KEEP(*(.exception_vectors_table.text));
    KEEP(*(.exception_vectors.text));
    /* Code marked as running out of IRAM */
    _iram_text_start = ABSOLUTE(.);
    
 *(.iram1 .iram1.*)
 *libclang_rt.builtins.a:_divsf3.*(.literal .literal.* .text .text.*)
 *libclang_rt.builtins.a:restore.*(.literal .literal.* .text .text.*)
 *libclang_rt.builtins.a:save.*(.literal .literal.* .text .text.*)
 *libesp_driver_dma.a:dma2d.*(.literal._dma2d_default_rx_isr .text._dma2d_default_rx_isr)
 *libesp_driver_dma.a:dma2d.*(.literal._dma2d_default_tx_isr .text._dma2d_default_tx_isr)
 *libesp_driver_dma.a:dma2d.*(.literal.acquire_free_channels_for_trans .text.acquire_free_channels_for_trans)
 *libesp_driver_dma.a:dma2d.*(.literal.dma2d_default_isr .text.dma2d_default_isr)
 *libesp_driver_dma.a:dma2d.*(.literal.free_up_channels .text.free_up_channels)
 *libesp_driver_dma.a:dw_gdma.*(.literal.dw_gdma_channel_default_isr .text.dw_gdma_channel_default_isr)
 *libesp_driver_dma.a:gdma.*(.literal.gdma_default_rx_isr .text.gdma_default_rx_isr)
 *libesp_driver_dma.a:gdma.*(.literal.gdma_default_tx_isr .text.gdma_default_tx_isr)
 *libesp_hal_dma.a:gdma_hal_ahb_v2.*(.literal.gdma_ahb_hal_clear_intr .text.gdma_ahb_hal_clear_intr)
 *libesp_hal_dma.a:gdma_hal_ahb_v2.*(.literal.gdma_ahb_hal_get_eof_desc_addr .text.gdma_ahb_hal_get_eof_desc_addr)
 *libesp_hal_dma.a:gdma_hal_ahb_v2.*(.literal.gdma_ahb_hal_is_tx_link_switch_event_supported .text.gdma_ahb_hal_is_tx_link_switch_event_supported)
 *libesp_hal_dma.a:gdma_hal_ahb_v2.*(.literal.gdma_ahb_hal_read_intr_status .text.gdma_ahb_hal_read_intr_status)
 *libesp_hal_dma.a:gdma_hal_axi.*(.literal.gdma_axi_hal_clear_intr .text.gdma_axi_hal_clear_intr)
 *libesp_hal_dma.a:gdma_hal_axi.*(.literal.gdma_axi_hal_get_eof_desc_addr .text.gdma_axi_hal_get_eof_desc_addr)
 *libesp_hal_dma.a:gdma_hal_axi.*(.literal.gdma_axi_hal_is_tx_link_switch_event_supported .text.gdma_axi_hal_is_tx_link_switch_event_supported)
 *libesp_hal_dma.a:gdma_hal_axi.*(.literal.gdma_axi_hal_read_intr_status .text.gdma_axi_hal_read_intr_status)
 *libesp_hal_dma.a:gdma_hal_top.*(.literal.gdma_hal_clear_intr .text.gdma_hal_clear_intr)
 *libesp_hal_dma.a:gdma_hal_top.*(.literal.gdma_hal_get_eof_desc_addr .text.gdma_hal_get_eof_desc_addr)
 *libesp_hal_dma.a:gdma_hal_top.*(.literal.gdma_hal_is_tx_link_switch_event_supported .text.gdma_hal_is_tx_link_switch_event_supported)
 *libesp_hal_dma.a:gdma_hal_top.*(.literal.gdma_hal_read_intr_status .text.gdma_hal_read_intr_status)
 *libesp_hal_gpio.a:gpio_hal.*(.literal.gpio_hal_isolate_in_sleep .text.gpio_hal_isolate_in_sleep)
 *libesp_hal_mspi.a:spi_flash_encrypt_hal_iram.*(.literal .literal.* .text .text.*)
 *libesp_hal_mspi.a:spi_flash_hal_gpspi.*(.literal .literal.* .text .text.*)
 *libesp_hal_mspi.a:spi_flash_hal_iram.*(.literal .literal.* .text .text.*)
 *libesp_hal_pmu.a:pmu_hal.*(.literal .literal.* .text .text.*)
 *libesp_hal_wdt.a:rom_patch.*(.literal .literal.* .text .text.*)
 *libesp_hw_support.a:clk_utils.*(.literal .literal.* .text .text.*)
 *libesp_hw_support.a:cpu.*(.literal.esp_cpu_compare_and_set .text.esp_cpu_compare_and_set)
 *libesp_hw_support.a:cpu.*(.literal.esp_cpu_reset .text.esp_cpu_reset)
 *libesp_hw_support.a:cpu.*(.literal.esp_cpu_stall .text.esp_cpu_stall)
 *libesp_hw_support.a:cpu.*(.literal.esp_cpu_unstall .text.esp_cpu_unstall)
 *libesp_hw_support.a:cpu.*(.literal.esp_cpu_wait_for_intr .text.esp_cpu_wait_for_intr)
 *libesp_hw_support.a:esp_clk_tree.*(.literal.esp_clk_tree_enable_power .text.esp_clk_tree_enable_power)
 *libesp_hw_support.a:esp_clk_tree.*(.literal.esp_clk_tree_enable_src .text.esp_clk_tree_enable_src)
 *libesp_hw_support.a:esp_clk_tree.*(.literal.esp_clk_tree_is_power_on .text.esp_clk_tree_is_power_on)
 *libesp_hw_support.a:esp_memory_utils.*(.literal .literal.* .text .text.*)
 *libesp_hw_support.a:mspi_timing_by_dqs.*(.literal .literal.* .text .text.*)
 *libesp_hw_support.a:mspi_timing_by_flash_delay.*(.literal .literal.* .text .text.*)
 *libesp_hw_support.a:mspi_timing_config.*(.literal .literal.* .text .text.*)
 *libesp_hw_support.a:mspi_timing_tuning.*(.literal .literal.* .text .text.*)
 *libesp_hw_support.a:periph_ctrl.*(.literal.periph_module_reset .text.periph_module_reset)
 *libesp_hw_support.a:periph_ctrl.*(.literal.periph_rcc_acquire_enter .text.periph_rcc_acquire_enter)
 *libesp_hw_support.a:periph_ctrl.*(.literal.periph_rcc_acquire_exit .text.periph_rcc_acquire_exit)
 *libesp_hw_support.a:periph_ctrl.*(.literal.periph_rcc_enter .text.periph_rcc_enter)
 *libesp_hw_support.a:periph_ctrl.*(.literal.periph_rcc_exit .text.periph_rcc_exit)
 *libesp_hw_support.a:periph_ctrl.*(.literal.periph_rcc_release_enter .text.periph_rcc_release_enter)
 *libesp_hw_support.a:periph_ctrl.*(.literal.periph_rcc_release_exit .text.periph_rcc_release_exit)
 *libesp_hw_support.a:pmu_pvt.*(.literal .literal.* .text .text.*)
 *libesp_hw_support.a:pmu_sleep.*(.literal .literal.* .text .text.*)
 *libesp_hw_support.a:regi2c_ctrl.*(.literal.regi2c_ctrl_read_reg .text.regi2c_ctrl_read_reg)
 *libesp_hw_support.a:regi2c_ctrl.*(.literal.regi2c_ctrl_read_reg_mask .text.regi2c_ctrl_read_reg_mask)
 *libesp_hw_support.a:regi2c_ctrl.*(.literal.regi2c_ctrl_write_reg .text.regi2c_ctrl_write_reg)
 *libesp_hw_support.a:regi2c_ctrl.*(.literal.regi2c_ctrl_write_reg_mask .text.regi2c_ctrl_write_reg_mask)
 *libesp_hw_support.a:regi2c_ctrl.*(.literal.regi2c_enter_critical .text.regi2c_enter_critical)
 *libesp_hw_support.a:regi2c_ctrl.*(.literal.regi2c_exit_critical .text.regi2c_exit_critical)
 *libesp_hw_support.a:rtc_clk.*(.literal .literal.* .text .text.*)
 *libesp_hw_support.a:rtc_time.*(.literal .literal.* .text .text.*)
 *libesp_hw_support.a:sleep_mspi.*(.literal .literal.* .text .text.*)
 *libesp_hw_support.a:systimer.*(.literal .literal.* .text .text.*)
 *libesp_libc.a:abort.*(.literal .literal.* .text .text.*)
 *libesp_libc.a:assert.*(.literal .literal.* .text .text.*)
 *libesp_libc.a:heap.*(.literal .literal.* .text .text.*)
 *libesp_libc.a:memcmp.*(.literal .literal.* .text .text.*)
 *libesp_libc.a:memcpy.*(.literal .literal.* .text .text.*)
 *libesp_libc.a:memmove.*(.literal .literal.* .text .text.*)
 *libesp_libc.a:stdatomic.*(.literal .literal.* .text .text.*)
 *libesp_libc.a:strcmp.*(.literal .literal.* .text .text.*)
 *libesp_libc.a:strcpy.*(.literal .literal.* .text .text.*)
 *libesp_libc.a:strncmp.*(.literal .literal.* .text .text.*)
 *libesp_libc.a:strncpy.*(.literal .literal.* .text .text.*)
 *libesp_mm.a:esp_cache_msync.*(.literal .literal.* .text .text.*)
 *libesp_mm.a:esp_cache_utils.*(.literal .literal.* .text .text.*)
 *libesp_rom.a:esp_rom_cache_writeback_esp32p4.*(.literal .literal.* .text .text.*)
 *libesp_rom.a:esp_rom_print.*(.literal .literal.* .text .text.*)
 *libesp_rom.a:esp_rom_spiflash.*(.literal .literal.* .text .text.*)
 *libesp_rom.a:esp_rom_sys.*(.literal .literal.* .text .text.*)
 *libesp_rom.a:esp_rom_systimer.*(.literal .literal.* .text .text.*)
 *libesp_system.a:esp_err.*(.literal .literal.* .text .text.*)
 *libesp_system.a:esp_system_chip.*(.literal.esp_system_abort .text.esp_system_abort)
 *libesp_system.a:freertos_hooks.*(.literal.esp_vApplicationTickHook .text.esp_vApplicationTickHook)
 *libesp_system.a:image_process.*(.literal .literal.* .text .text.*)
 *libesp_system.a:panic.*(.literal.panic_abort .text.panic_abort)
 *libesp_system.a:reset_reason.*(.literal.esp_reset_reason_set_hint .text.esp_reset_reason_set_hint)
 *libesp_system.a:system_internal.*(.literal.esp_restart_noos .text.esp_restart_noos)
 *libesp_system.a:system_internal.*(.literal.esp_system_reset_modules_on_exit .text.esp_system_reset_modules_on_exit)
 *libesp_system.a:system_time.*(.literal.esp_system_get_time .text.esp_system_get_time)
 *libesp_system.a:system_time.*(.literal.esp_system_get_time_resolution .text.esp_system_get_time_resolution)
 *libesp_system.a:ubsan.*(.literal .literal.* .text .text.*)
 *libfreertos.a:event_groups.*(.literal.xEventGroupGetBitsFromISR .text.xEventGroupGetBitsFromISR)
 *libfreertos.a:list.*(.literal.uxListRemove .text.uxListRemove)
 *libfreertos.a:list.*(.literal.vListInsertEnd .text.vListInsertEnd)
 *libfreertos.a:port.*(.literal.vPortAssertIfInISR .text.vPortAssertIfInISR)
 *libfreertos.a:port.*(.literal.vPortClearInterruptMaskFromISR .text.vPortClearInterruptMaskFromISR)
 *libfreertos.a:port.*(.literal.vPortCoprocUsedInISR .text.vPortCoprocUsedInISR)
 *libfreertos.a:port.*(.literal.vPortEnterCritical .text.vPortEnterCritical)
 *libfreertos.a:port.*(.literal.vPortExitCritical .text.vPortExitCritical)
 *libfreertos.a:port.*(.literal.vPortExitCriticalMultiCore .text.vPortExitCriticalMultiCore)
 *libfreertos.a:port.*(.literal.vPortSetStackWatchpoint .text.vPortSetStackWatchpoint)
 *libfreertos.a:port.*(.literal.vPortYield .text.vPortYield)
 *libfreertos.a:port.*(.literal.vPortYieldFromISR .text.vPortYieldFromISR)
 *libfreertos.a:port.*(.literal.vPortYieldOtherCore .text.vPortYieldOtherCore)
 *libfreertos.a:port.*(.literal.xPortEnterCriticalTimeout .text.xPortEnterCriticalTimeout)
 *libfreertos.a:port.*(.literal.xPortFPUContextIsDirty .text.xPortFPUContextIsDirty)
 *libfreertos.a:port.*(.literal.xPortInIsrContext .text.xPortInIsrContext)
 *libfreertos.a:port.*(.literal.xPortInterruptedFromISRContext .text.xPortInterruptedFromISRContext)
 *libfreertos.a:port.*(.literal.xPortSetInterruptMaskFromISR .text.xPortSetInterruptMaskFromISR)
 *libfreertos.a:port_systick.*(.text .text.SysTickIsrHandler .text.xPortSysTickHandler)
 *libfreertos.a:portasm.*(.literal .literal.* .text .text.*)
 *libfreertos.a:queue.*(.literal.prvCopyDataFromQueue .text.prvCopyDataFromQueue)
 *libfreertos.a:queue.*(.literal.prvCopyDataToQueue .text.prvCopyDataToQueue)
 *libfreertos.a:queue.*(.literal.prvNotifyQueueSetContainer .text.prvNotifyQueueSetContainer)
 *libfreertos.a:queue.*(.literal.uxQueueMessagesWaitingFromISR .text.uxQueueMessagesWaitingFromISR)
 *libfreertos.a:queue.*(.literal.xQueueGenericSendFromISR .text.xQueueGenericSendFromISR)
 *libfreertos.a:queue.*(.literal.xQueueGetMutexHolderFromISR .text.xQueueGetMutexHolderFromISR)
 *libfreertos.a:queue.*(.literal.xQueueGiveFromISR .text.xQueueGiveFromISR)
 *libfreertos.a:queue.*(.literal.xQueueIsQueueEmptyFromISR .text.xQueueIsQueueEmptyFromISR)
 *libfreertos.a:queue.*(.literal.xQueueIsQueueFullFromISR .text.xQueueIsQueueFullFromISR)
 *libfreertos.a:queue.*(.literal.xQueuePeekFromISR .text.xQueuePeekFromISR)
 *libfreertos.a:queue.*(.literal.xQueueReceiveFromISR .text.xQueueReceiveFromISR)
 *libfreertos.a:queue.*(.literal.xQueueSelectFromSetFromISR .text.xQueueSelectFromSetFromISR)
 *libfreertos.a:stream_buffer.*(.literal.prvBytesInBuffer .text.prvBytesInBuffer)
 *libfreertos.a:stream_buffer.*(.literal.prvReadMessageFromBuffer .text.prvReadMessageFromBuffer)
 *libfreertos.a:stream_buffer.*(.literal.prvWriteMessageToBuffer .text.prvWriteMessageToBuffer)
 *libfreertos.a:stream_buffer.*(.literal.xStreamBufferReceiveCompletedFromISR .text.xStreamBufferReceiveCompletedFromISR)
 *libfreertos.a:stream_buffer.*(.literal.xStreamBufferReceiveFromISR .text.xStreamBufferReceiveFromISR)
 *libfreertos.a:stream_buffer.*(.literal.xStreamBufferSendCompletedFromISR .text.xStreamBufferSendCompletedFromISR)
 *libfreertos.a:stream_buffer.*(.literal.xStreamBufferSendFromISR .text.xStreamBufferSendFromISR)
 *libfreertos.a:tasks.*(.literal.prvCheckTaskCanBeScheduledSMP .text.prvCheckTaskCanBeScheduledSMP)
 *libfreertos.a:tasks.*(.literal.prvIsYieldRequiredSMP .text.prvIsYieldRequiredSMP)
 *libfreertos.a:tasks.*(.literal.prvResetNextTaskUnblockTime .text.prvResetNextTaskUnblockTime)
 *libfreertos.a:tasks.*(.literal.prvSelectHighestPriorityTaskSMP .text.prvSelectHighestPriorityTaskSMP)
 *libfreertos.a:tasks.*(.literal.prvTaskIsTaskSuspended .text.prvTaskIsTaskSuspended)
 *libfreertos.a:tasks.*(.literal.uxTaskPriorityGetFromISR .text.uxTaskPriorityGetFromISR)
 *libfreertos.a:tasks.*(.literal.vTaskGenericNotifyGiveFromISR .text.vTaskGenericNotifyGiveFromISR)
 *libfreertos.a:tasks.*(.literal.vTaskGetSnapshot .text.vTaskGetSnapshot)
 *libfreertos.a:tasks.*(.literal.vTaskSwitchContext .text.vTaskSwitchContext)
 *libfreertos.a:tasks.*(.literal.xTaskGenericNotifyFromISR .text.xTaskGenericNotifyFromISR)
 *libfreertos.a:tasks.*(.literal.xTaskGetSchedulerState .text.xTaskGetSchedulerState)
 *libfreertos.a:tasks.*(.literal.xTaskGetTickCount .text.xTaskGetTickCount)
 *libfreertos.a:tasks.*(.literal.xTaskGetTickCountFromISR .text.xTaskGetTickCountFromISR)
 *libfreertos.a:tasks.*(.literal.xTaskIncrementTick .text.xTaskIncrementTick)
 *libfreertos.a:tasks.*(.literal.xTaskIncrementTickOtherCores .text.xTaskIncrementTickOtherCores)
 *libfreertos.a:tasks.*(.literal.xTaskRemoveFromEventList .text.xTaskRemoveFromEventList)
 *libfreertos.a:tasks.*(.literal.xTaskResumeFromISR .text.xTaskResumeFromISR)
 *libfreertos.a:timers.*(.literal.xTimerGenericCommand .text.xTimerGenericCommand)
 *libfreertos.a:timers.*(.literal.xTimerPendFunctionCallFromISR .text.xTimerPendFunctionCallFromISR)
 *libgcc.a:_divsf3.*(.literal .literal.* .text .text.*)
 *libgcc.a:lib2funcs.*(.literal .literal.* .text .text.*)
 *libgcc.a:save-restore.*(.literal .literal.* .text .text.*)
 *libgcov.a:(.literal .literal.* .text .text.*)
 *libhal.a:cache_hal.*(.literal .literal.* .text .text.*)
 *libhal.a:mmu_hal.*(.literal .literal.* .text .text.*)
 *libheap.a:multi_heap.*(.literal.assert_valid_block .text.assert_valid_block)
 *libheap.a:multi_heap.*(.literal.multi_heap_aligned_alloc_impl .text.multi_heap_aligned_alloc_impl)
 *libheap.a:multi_heap.*(.literal.multi_heap_aligned_alloc_impl_offs .text.multi_heap_aligned_alloc_impl_offs)
 *libheap.a:multi_heap.*(.literal.multi_heap_aligned_alloc_offs .text.multi_heap_aligned_alloc_offs)
 *libheap.a:multi_heap.*(.literal.multi_heap_free_impl .text.multi_heap_free_impl)
 *libheap.a:multi_heap.*(.literal.multi_heap_get_allocated_size_impl .text.multi_heap_get_allocated_size_impl)
 *libheap.a:multi_heap.*(.literal.multi_heap_get_block_address_impl .text.multi_heap_get_block_address_impl)
 *libheap.a:multi_heap.*(.literal.multi_heap_get_first_block .text.multi_heap_get_first_block)
 *libheap.a:multi_heap.*(.literal.multi_heap_get_full_block_size .text.multi_heap_get_full_block_size)
 *libheap.a:multi_heap.*(.literal.multi_heap_get_next_block .text.multi_heap_get_next_block)
 *libheap.a:multi_heap.*(.literal.multi_heap_internal_lock .text.multi_heap_internal_lock)
 *libheap.a:multi_heap.*(.literal.multi_heap_internal_unlock .text.multi_heap_internal_unlock)
 *libheap.a:multi_heap.*(.literal.multi_heap_is_free .text.multi_heap_is_free)
 *libheap.a:multi_heap.*(.literal.multi_heap_malloc_impl .text.multi_heap_malloc_impl)
 *libheap.a:multi_heap.*(.literal.multi_heap_realloc_impl .text.multi_heap_realloc_impl)
 *libheap.a:multi_heap.*(.literal.multi_heap_set_lock .text.multi_heap_set_lock)
 *libheap.a:tlsf.*(.literal.tlsf_alloc_overhead .text.tlsf_alloc_overhead)
 *libheap.a:tlsf.*(.literal.tlsf_block_size .text.tlsf_block_size)
 *libheap.a:tlsf.*(.literal.tlsf_free .text.tlsf_free)
 *libheap.a:tlsf.*(.literal.tlsf_get_pool .text.tlsf_get_pool)
 *libheap.a:tlsf.*(.literal.tlsf_malloc .text.tlsf_malloc)
 *libheap.a:tlsf.*(.literal.tlsf_memalign .text.tlsf_memalign)
 *libheap.a:tlsf.*(.literal.tlsf_memalign_offs .text.tlsf_memalign_offs)
 *libheap.a:tlsf.*(.literal.tlsf_realloc .text.tlsf_realloc)
 *libheap.a:tlsf.*(.literal.tlsf_size .text.tlsf_size)
 *liblog.a:log.*(.literal .literal.* .text .text.*)
 *liblog.a:log_format_text.*(.literal .literal.* .text .text.*)
 *liblog.a:log_lock.*(.literal .literal.* .text .text.*)
 *liblog.a:log_print.*(.literal .literal.* .text .text.*)
 *liblog.a:log_timestamp.*(.literal.esp_log_early_timestamp .text.esp_log_early_timestamp)
 *liblog.a:log_timestamp.*(.literal.esp_log_timestamp .text.esp_log_timestamp)
 *liblog.a:log_timestamp_common.*(.literal .literal.* .text .text.*)
 *liblog.a:log_write.*(.literal.esp_log_write .text.esp_log_write)
 *liblog.a:log_write.*(.literal.esp_log_writev .text.esp_log_writev)
 *liblog.a:tag_log_level.*(.literal.esp_log_level_get_timeout .text.esp_log_level_get_timeout)
 *liblog.a:util.*(.literal .literal.* .text .text.*)
 *libriscv.a:interrupt.*(.text .text._global_interrupt_handler .text.intr_get_item .text.intr_handler_get_arg)
 *libriscv.a:rv_utils.*(.literal .literal.* .text .text.*)
 *libriscv.a:vectors.*(.literal .literal.* .text .text.*)
 *libsoc.a:lldesc.*(.literal .literal.* .text .text.*)
 *libspi_flash.a:esp_flash_api.*(.literal.check_chip_pointer_default .text.check_chip_pointer_default)
 *libspi_flash.a:esp_flash_api.*(.literal.detect_spi_flash_chip .text.detect_spi_flash_chip)
 *libspi_flash.a:esp_flash_api.*(.literal.esp_flash_chip_driver_initialized .text.esp_flash_chip_driver_initialized)
 *libspi_flash.a:esp_flash_api.*(.literal.esp_flash_erase_chip .text.esp_flash_erase_chip)
 *libspi_flash.a:esp_flash_api.*(.literal.esp_flash_erase_region .text.esp_flash_erase_region)
 *libspi_flash.a:esp_flash_api.*(.literal.esp_flash_get_chip_write_protect .text.esp_flash_get_chip_write_protect)
 *libspi_flash.a:esp_flash_api.*(.literal.esp_flash_get_io_mode .text.esp_flash_get_io_mode)
 *libspi_flash.a:esp_flash_api.*(.literal.esp_flash_get_physical_size .text.esp_flash_get_physical_size)
 *libspi_flash.a:esp_flash_api.*(.literal.esp_flash_get_protected_region .text.esp_flash_get_protected_region)
 *libspi_flash.a:esp_flash_api.*(.literal.esp_flash_get_size .text.esp_flash_get_size)
 *libspi_flash.a:esp_flash_api.*(.literal.esp_flash_init .text.esp_flash_init)
 *libspi_flash.a:esp_flash_api.*(.literal.esp_flash_init_main .text.esp_flash_init_main)
 *libspi_flash.a:esp_flash_api.*(.literal.esp_flash_is_quad_mode .text.esp_flash_is_quad_mode)
 *libspi_flash.a:esp_flash_api.*(.literal.esp_flash_read .text.esp_flash_read)
 *libspi_flash.a:esp_flash_api.*(.literal.esp_flash_read_encrypted .text.esp_flash_read_encrypted)
 *libspi_flash.a:esp_flash_api.*(.literal.esp_flash_set_chip_write_protect .text.esp_flash_set_chip_write_protect)
 *libspi_flash.a:esp_flash_api.*(.literal.esp_flash_set_io_mode .text.esp_flash_set_io_mode)
 *libspi_flash.a:esp_flash_api.*(.literal.esp_flash_set_protected_region .text.esp_flash_set_protected_region)
 *libspi_flash.a:esp_flash_api.*(.literal.esp_flash_write .text.esp_flash_write)
 *libspi_flash.a:esp_flash_api.*(.literal.esp_flash_write_encrypted .text.esp_flash_write_encrypted)
 *libspi_flash.a:esp_flash_api.*(.literal.flash_end_flush_cache .text.flash_end_flush_cache)
 *libspi_flash.a:esp_flash_api.*(.literal.read_unique_id .text.read_unique_id)
 *libspi_flash.a:esp_flash_api.*(.literal.spiflash_end_default .text.spiflash_end_default)
 *libspi_flash.a:esp_flash_api.*(.literal.spiflash_start_core .text.spiflash_start_core)
 *libspi_flash.a:esp_flash_api.*(.literal.spiflash_start_default .text.spiflash_start_default)
 *libspi_flash.a:flash_brownout_hook.*(.literal .literal.* .text .text.*)
 *libspi_flash.a:memspi_host_driver.*(.literal .literal.* .text .text.*)
 *libspi_flash.a:spi_flash_chip_boya.*(.literal .literal.* .text .text.*)
 *libspi_flash.a:spi_flash_chip_gd.*(.literal .literal.* .text .text.*)
 *libspi_flash.a:spi_flash_chip_generic.*(.literal .literal.* .text .text.*)
 *libspi_flash.a:spi_flash_chip_issi.*(.literal .literal.* .text .text.*)
 *libspi_flash.a:spi_flash_chip_mxic.*(.literal .literal.* .text .text.*)
 *libspi_flash.a:spi_flash_chip_th.*(.literal .literal.* .text .text.*)
 *libspi_flash.a:spi_flash_chip_winbond.*(.literal .literal.* .text .text.*)
 *libspi_flash.a:spi_flash_hpm_enable.*(.literal .literal.* .text .text.*)
 *libspi_flash.a:spi_flash_os_func_app.*(.literal.delay_us .text.delay_us)
 *libspi_flash.a:spi_flash_os_func_app.*(.literal.get_buffer_malloc .text.get_buffer_malloc)
 *libspi_flash.a:spi_flash_os_func_app.*(.literal.main_flash_op_status .text.main_flash_op_status)
 *libspi_flash.a:spi_flash_os_func_app.*(.literal.main_flash_region_protected .text.main_flash_region_protected)
 *libspi_flash.a:spi_flash_os_func_app.*(.literal.release_buffer_malloc .text.release_buffer_malloc)
 *libspi_flash.a:spi_flash_os_func_app.*(.literal.spi23_end .text.spi23_end)
 *libspi_flash.a:spi_flash_os_func_app.*(.literal.spi23_start .text.spi23_start)
 *libspi_flash.a:spi_flash_os_func_app.*(.literal.spi_flash_os_check_yield .text.spi_flash_os_check_yield)
 *libspi_flash.a:spi_flash_os_func_app.*(.literal.spi_flash_os_yield .text.spi_flash_os_yield)
 *libspi_flash.a:spi_flash_os_func_noos.*(.literal.delay_us .text.delay_us)
 *libspi_flash.a:spi_flash_os_func_noos.*(.literal.esp_flash_app_disable_os_functions .text.esp_flash_app_disable_os_functions)
 *libspi_flash.a:spi_flash_os_func_noos.*(.literal.get_temp_buffer_not_supported .text.get_temp_buffer_not_supported)
 *libspi_flash.a:spi_flash_wrap.*(.literal .literal.* .text .text.*)
 mutable[iram0_text]
  } > iram_text_seg
  /* Marks the end of IRAM code segment */
  .iram0.text_end (NOLOAD) :
  {
    /* Padding for possible CPU prefetch + alignment for PMS split lines */
    . += 0;
    . = ALIGN(0);
    /* Align the end of code region as per PMP region granularity */
    . = ALIGN(128);
    /* iram_end_test section exists for use by memprot unit tests only */
    *(.iram_end_test)
    
 . = ALIGN(4); 
 _iram_text_end = ABSOLUTE(.);
  } > iram_text_seg
 .iram0.data :
  {
    
 . = ALIGN(16); 
 _iram_data_start = ABSOLUTE(.);
    
 *(.iram.data .iram.data.*)
 mutable[iram0_data]
    _iram_data_end = ABSOLUTE(.);
  } > iram_text_seg
  .iram0.bss (NOLOAD) :
  {
    
 . = ALIGN(16); 
 _iram_bss_start = ABSOLUTE(.);
    
 *(.iram.bss .iram.bss.*)
 mutable[iram0_bss]
    _iram_bss_end = ABSOLUTE(.);
  } > iram_text_seg
  .iram0.end (NOLOAD) :
  {
    
 . = ALIGN(16); 
 _iram_end = ABSOLUTE(.);
  } > iram_text_seg
ASSERT(((_iram_end - ORIGIN(iram_text_seg)) <= LENGTH(iram_text_seg)),
          "IRAM0 segment data does not fit.")
/*
 * SPDX-FileCopyrightText: 2021-2024 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: Apache-2.0
 */
/* CPU instruction prefetch padding size for flash mmap scenario */
/*
 * PMP region granularity size
 * Software may determine the PMP granularity by writing zero to pmp0cfg, then writing all ones
 * to pmpaddr0, then reading back pmpaddr0. If G is the index of the least-significant bit set,
 * the PMP granularity is 2^G+2 bytes.
 */
/* CPU instruction prefetch padding size for memory protection scenario */
/* Memory alignment size for PMS */
    /* rtc timer data (s_rtc_timer_retain_mem, see esp_clk.c files). For rtc_timer_data_in_rtc_mem section. */
  .dram0.dummy (NOLOAD) :
  {
    /**
     * Reserve DRAM space for shared D/IRAM memory configuration.
     *
     * On certain ESP chips, the same physical SRAM is accessible via two
     * different virtual address ranges:
     *   - IRAM: 0x4xxxxxxx
     *   - DRAM: 0x3Fxxxxxx
     *
     * While the virtual addresses differ, both ranges map to the same physical
     * memory.
     *
     * When `_iram_dram_shared` is defined, it indicates this configuration exists.
     * We must advance the DRAM location counter past the region used by IRAM code
     * to prevent DRAM data from physically overwriting executable IRAM code.
     */
    . = DEFINED(_iram_dram_shared) ? ORIGIN(dram_seg) + (_iram_end - _iram_start) : .;
  } > dram_seg
  .dram0.data_start :
  {
    _data_start = .;
  } > dram_seg
  .dram0.data :
  {
    *(.gnu.linkonce.d.*)
    *(.data1)
    __global_pointer$ = . + 0x800;
    *(.sdata)
    *(.sdata.*)
    *(.gnu.linkonce.s.*)
    *(.gnu.linkonce.s2.*)
    *(.jcr)
    
 *(.data .data.*)
 *(.dram1 .dram1.*)
 *libclang_rt.builtins.a:_divsf3.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libclang_rt.builtins.a:restore.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libclang_rt.builtins.a:save.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_driver_dma.a:dma2d.*(.rodata._dma2d_default_rx_isr .rodata._dma2d_default_rx_isr.str1.4 .sdata2._dma2d_default_rx_isr .srodata._dma2d_default_rx_isr)
 *libesp_driver_dma.a:dma2d.*(.rodata.free_up_channels .rodata.free_up_channels.str1.4 .sdata2.free_up_channels .srodata.free_up_channels)
 *libesp_hal_mspi.a:spi_flash_encrypt_hal_iram.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_hal_mspi.a:spi_flash_hal_gpspi.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_hal_mspi.a:spi_flash_hal_iram.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_hal_pmu.a:pmu_hal.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_hal_wdt.a:rom_patch.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_hw_support.a:clk_utils.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_hw_support.a:cpu.*(.rodata.esp_cpu_stall .rodata.esp_cpu_stall.str1.4 .sdata2.esp_cpu_stall .srodata.esp_cpu_stall)
 *libesp_hw_support.a:esp_clk_tree.*(.rodata.esp_clk_tree_enable_src .rodata.esp_clk_tree_enable_src.str1.4 .sdata2.esp_clk_tree_enable_src .srodata.esp_clk_tree_enable_src)
 *libesp_hw_support.a:esp_memory_utils.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_hw_support.a:mspi_timing_by_dqs.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_hw_support.a:mspi_timing_by_flash_delay.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_hw_support.a:mspi_timing_config.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_hw_support.a:mspi_timing_tuning.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_hw_support.a:pmu_pvt.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_hw_support.a:pmu_sleep.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_hw_support.a:rtc_clk.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_hw_support.a:sleep_mspi.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_hw_support.a:systimer.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_libc.a:abort.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_libc.a:assert.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_libc.a:heap.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_libc.a:memcmp.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_libc.a:memcpy.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_libc.a:memmove.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_libc.a:stdatomic.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_libc.a:strcmp.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_libc.a:strcpy.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_libc.a:strncmp.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_libc.a:strncpy.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_mm.a:esp_cache_msync.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_mm.a:esp_cache_utils.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_rom.a:esp_rom_cache_writeback_esp32p4.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_rom.a:esp_rom_print.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_rom.a:esp_rom_spiflash.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_rom.a:esp_rom_sys.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_rom.a:esp_rom_systimer.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_system.a:esp_err.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_system.a:image_process.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libesp_system.a:reset_reason.*(.rodata.esp_reset_reason_set_hint .rodata.esp_reset_reason_set_hint.str1.4 .sdata2.esp_reset_reason_set_hint .srodata.esp_reset_reason_set_hint)
 *libesp_system.a:system_internal.*(.rodata.esp_system_reset_modules_on_exit .rodata.esp_system_reset_modules_on_exit.str1.4 .sdata2.esp_system_reset_modules_on_exit .srodata.esp_system_reset_modules_on_exit)
 *libesp_system.a:ubsan.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libgcc.a:_divsf3.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libgcc.a:save-restore.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libgcov.a:(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libhal.a:cache_hal.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libhal.a:mmu_hal.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libheap.a:multi_heap.*(.rodata.assert_valid_block .rodata.assert_valid_block.str1.4 .sdata2.assert_valid_block .srodata.assert_valid_block)
 *libheap.a:multi_heap.*(.rodata.multi_heap_get_first_block .rodata.multi_heap_get_first_block.str1.4 .sdata2.multi_heap_get_first_block .srodata.multi_heap_get_first_block)
 *libheap.a:multi_heap.*(.rodata.multi_heap_get_next_block .rodata.multi_heap_get_next_block.str1.4 .sdata2.multi_heap_get_next_block .srodata.multi_heap_get_next_block)
 *libheap.a:tlsf.*(.rodata.tlsf_free .rodata.tlsf_free.str1.4 .sdata2.tlsf_free .srodata.tlsf_free)
 *libheap.a:tlsf.*(.rodata.tlsf_malloc .rodata.tlsf_malloc.str1.4 .sdata2.tlsf_malloc .srodata.tlsf_malloc)
 *libheap.a:tlsf.*(.rodata.tlsf_memalign_offs .rodata.tlsf_memalign_offs.str1.4 .sdata2.tlsf_memalign_offs .srodata.tlsf_memalign_offs)
 *libheap.a:tlsf.*(.rodata.tlsf_realloc .rodata.tlsf_realloc.str1.4 .sdata2.tlsf_realloc .srodata.tlsf_realloc)
 *liblog.a:log.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *liblog.a:log_format_text.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *liblog.a:log_lock.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *liblog.a:log_print.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *liblog.a:log_timestamp_common.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *liblog.a:util.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libsoc.a:lldesc.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libspi_flash.a:flash_brownout_hook.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libspi_flash.a:memspi_host_driver.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libspi_flash.a:spi_flash_chip_boya.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libspi_flash.a:spi_flash_chip_gd.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libspi_flash.a:spi_flash_chip_generic.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libspi_flash.a:spi_flash_chip_issi.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libspi_flash.a:spi_flash_chip_mxic.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libspi_flash.a:spi_flash_chip_th.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libspi_flash.a:spi_flash_chip_winbond.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libspi_flash.a:spi_flash_hpm_enable.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 *libspi_flash.a:spi_flash_os_func_app.*(.rodata.spi_flash_os_check_yield .rodata.spi_flash_os_check_yield.str1.4 .sdata2.spi_flash_os_check_yield .srodata.spi_flash_os_check_yield)
 *libspi_flash.a:spi_flash_wrap.*(.rodata .rodata.* .sdata2 .sdata2.* .srodata .srodata.*)
 mutable[dram0_data]
    _data_end = ABSOLUTE(.);
  } > dram_seg
  /**
   * This section holds data that should not be initialized at power up.
   * The section is located in Internal SRAM memory region. The macro _NOINIT
   * can be used as attribute to place data into this section.
   * See the "esp_attr.h" file for more information.
   */
  .noinit (NOLOAD) :
  {
    
 . = ALIGN(4); 
 _noinit_start = ABSOLUTE(.);
    
 mutable[noinit]
    *(.noinit .noinit.*)
    
 . = ALIGN(4); 
 _noinit_end = ABSOLUTE(.);
  } > dram_seg
  /* Shared RAM */
  .dram0.bss (NOLOAD) :
  {
    
 . = ALIGN(8); 
 _bss_start = ABSOLUTE(.);
    
 *(.bss .bss.*)
 *(.dynbss .dynsbss .gnu.linkonce.b .gnu.linkonce.b.* .gnu.linkonce.sb .gnu.linkonce.sb.* .gnu.linkonce.sb2 .gnu.linkonce.sb2.* .sbss .sbss.* .sbss2 .sbss2.* .scommon .share.mem)
 *(.ext_ram.bss .ext_ram.bss.*)
 *(COMMON)
 mutable[dram0_bss]
    
 . = ALIGN(8); 
 _bss_end = ABSOLUTE(.);
  } > dram_seg
/*
 * SPDX-FileCopyrightText: 2021-2024 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: Apache-2.0
 */
/* CPU instruction prefetch padding size for flash mmap scenario */
/*
 * PMP region granularity size
 * Software may determine the PMP granularity by writing zero to pmp0cfg, then writing all ones
 * to pmpaddr0, then reading back pmpaddr0. If G is the index of the least-significant bit set,
 * the PMP granularity is 2^G+2 bytes.
 */
/* CPU instruction prefetch padding size for memory protection scenario */
/* Memory alignment size for PMS */
    /* rtc timer data (s_rtc_timer_retain_mem, see esp_clk.c files). For rtc_timer_data_in_rtc_mem section. */
  .flash.text :
  {
    _stext = .;
    /**
     * Mark the start of flash.text.
     * This can be used by the MMU driver to maintain the virtual address.
     */
    _instruction_reserved_start = ABSOLUTE(.);
    _text_start = ABSOLUTE(.);
    
 *(EXCLUDE_FILE(*libgcov.a *libclang_rt.builtins.a:_divsf3.* *libclang_rt.builtins.a:restore.* *libclang_rt.builtins.a:save.* *libesp_driver_dma.a:dma2d.* *libesp_driver_dma.a:dw_gdma.* *libesp_driver_dma.a:gdma.* *libesp_hal_dma.a:gdma_hal_ahb_v2.* *libesp_hal_dma.a:gdma_hal_axi.* *libesp_hal_dma.a:gdma_hal_top.* *libesp_hal_gpio.a:gpio_hal.* *libesp_hal_mspi.a:spi_flash_encrypt_hal_iram.* *libesp_hal_mspi.a:spi_flash_hal_gpspi.* *libesp_hal_mspi.a:spi_flash_hal_iram.* *libesp_hal_pmu.a:pmu_hal.* *libesp_hal_wdt.a:rom_patch.* *libesp_hw_support.a:clk_utils.* *libesp_hw_support.a:cpu.* *libesp_hw_support.a:esp_clk_tree.* *libesp_hw_support.a:esp_memory_utils.* *libesp_hw_support.a:mspi_timing_by_dqs.* *libesp_hw_support.a:mspi_timing_by_flash_delay.* *libesp_hw_support.a:mspi_timing_config.* *libesp_hw_support.a:mspi_timing_tuning.* *libesp_hw_support.a:periph_ctrl.* *libesp_hw_support.a:pmu_pvt.* *libesp_hw_support.a:pmu_sleep.* *libesp_hw_support.a:regi2c_ctrl.* *libesp_hw_support.a:rtc_clk.* *libesp_hw_support.a:rtc_time.* *libesp_hw_support.a:sleep_mspi.* *libesp_hw_support.a:systimer.* *libesp_libc.a:abort.* *libesp_libc.a:assert.* *libesp_libc.a:heap.* *libesp_libc.a:memcmp.* *libesp_libc.a:memcpy.* *libesp_libc.a:memmove.* *libesp_libc.a:stdatomic.* *libesp_libc.a:strcmp.* *libesp_libc.a:strcpy.* *libesp_libc.a:strncmp.* *libesp_libc.a:strncpy.* *libesp_mm.a:esp_cache_msync.* *libesp_mm.a:esp_cache_utils.* *libesp_rom.a:esp_rom_cache_writeback_esp32p4.* *libesp_rom.a:esp_rom_print.* *libesp_rom.a:esp_rom_spiflash.* *libesp_rom.a:esp_rom_sys.* *libesp_rom.a:esp_rom_systimer.* *libesp_system.a:esp_err.* *libesp_system.a:esp_system_chip.* *libesp_system.a:freertos_hooks.* *libesp_system.a:image_process.* *libesp_system.a:panic.* *libesp_system.a:reset_reason.* *libesp_system.a:system_internal.* *libesp_system.a:system_time.* *libesp_system.a:ubsan.* *libfreertos.a:event_groups.* *libfreertos.a:list.* *libfreertos.a:port.* *libfreertos.a:port_systick.* *libfreertos.a:portasm.* *libfreertos.a:queue.* *libfreertos.a:stream_buffer.* *libfreertos.a:tasks.* *libfreertos.a:timers.* *libgcc.a:_divsf3.* *libgcc.a:lib2funcs.* *libgcc.a:save-restore.* *libhal.a:cache_hal.* *libhal.a:mmu_hal.* *libheap.a:multi_heap.* *libheap.a:tlsf.* *liblog.a:log.* *liblog.a:log_format_text.* *liblog.a:log_lock.* *liblog.a:log_print.* *liblog.a:log_timestamp.* *liblog.a:log_timestamp_common.* *liblog.a:log_write.* *liblog.a:tag_log_level.* *liblog.a:util.* *libriscv.a:interrupt.* *libriscv.a:rv_utils.* *libriscv.a:vectors.* *libsoc.a:lldesc.* *libspi_flash.a:esp_flash_api.* *libspi_flash.a:flash_brownout_hook.* *libspi_flash.a:memspi_host_driver.* *libspi_flash.a:spi_flash_chip_boya.* *libspi_flash.a:spi_flash_chip_gd.* *libspi_flash.a:spi_flash_chip_generic.* *libspi_flash.a:spi_flash_chip_issi.* *libspi_flash.a:spi_flash_chip_mxic.* *libspi_flash.a:spi_flash_chip_th.* *libspi_flash.a:spi_flash_chip_winbond.* *libspi_flash.a:spi_flash_hpm_enable.* *libspi_flash.a:spi_flash_os_func_app.* *libspi_flash.a:spi_flash_os_func_noos.* *libspi_flash.a:spi_flash_wrap.*) .literal EXCLUDE_FILE(*libgcov.a *libclang_rt.builtins.a:_divsf3.* *libclang_rt.builtins.a:restore.* *libclang_rt.builtins.a:save.* *libesp_driver_dma.a:dma2d.* *libesp_driver_dma.a:dw_gdma.* *libesp_driver_dma.a:gdma.* *libesp_hal_dma.a:gdma_hal_ahb_v2.* *libesp_hal_dma.a:gdma_hal_axi.* *libesp_hal_dma.a:gdma_hal_top.* *libesp_hal_gpio.a:gpio_hal.* *libesp_hal_mspi.a:spi_flash_encrypt_hal_iram.* *libesp_hal_mspi.a:spi_flash_hal_gpspi.* *libesp_hal_mspi.a:spi_flash_hal_iram.* *libesp_hal_pmu.a:pmu_hal.* *libesp_hal_wdt.a:rom_patch.* *libesp_hw_support.a:clk_utils.* *libesp_hw_support.a:cpu.* *libesp_hw_support.a:esp_clk_tree.* *libesp_hw_support.a:esp_memory_utils.* *libesp_hw_support.a:mspi_timing_by_dqs.* *libesp_hw_support.a:mspi_timing_by_flash_delay.* *libesp_hw_support.a:mspi_timing_config.* *libesp_hw_support.a:mspi_timing_tuning.* *libesp_hw_support.a:periph_ctrl.* *libesp_hw_support.a:pmu_pvt.* *libesp_hw_support.a:pmu_sleep.* *libesp_hw_support.a:regi2c_ctrl.* *libesp_hw_support.a:rtc_clk.* *libesp_hw_support.a:rtc_time.* *libesp_hw_support.a:sleep_mspi.* *libesp_hw_support.a:systimer.* *libesp_libc.a:abort.* *libesp_libc.a:assert.* *libesp_libc.a:heap.* *libesp_libc.a:memcmp.* *libesp_libc.a:memcpy.* *libesp_libc.a:memmove.* *libesp_libc.a:stdatomic.* *libesp_libc.a:strcmp.* *libesp_libc.a:strcpy.* *libesp_libc.a:strncmp.* *libesp_libc.a:strncpy.* *libesp_mm.a:esp_cache_msync.* *libesp_mm.a:esp_cache_utils.* *libesp_rom.a:esp_rom_cache_writeback_esp32p4.* *libesp_rom.a:esp_rom_print.* *libesp_rom.a:esp_rom_spiflash.* *libesp_rom.a:esp_rom_sys.* *libesp_rom.a:esp_rom_systimer.* *libesp_system.a:esp_err.* *libesp_system.a:esp_system_chip.* *libesp_system.a:freertos_hooks.* *libesp_system.a:image_process.* *libesp_system.a:panic.* *libesp_system.a:reset_reason.* *libesp_system.a:system_internal.* *libesp_system.a:system_time.* *libesp_system.a:ubsan.* *libfreertos.a:event_groups.* *libfreertos.a:list.* *libfreertos.a:port.* *libfreertos.a:port_systick.* *libfreertos.a:portasm.* *libfreertos.a:queue.* *libfreertos.a:stream_buffer.* *libfreertos.a:tasks.* *libfreertos.a:timers.* *libgcc.a:_divsf3.* *libgcc.a:lib2funcs.* *libgcc.a:save-restore.* *libhal.a:cache_hal.* *libhal.a:mmu_hal.* *libheap.a:multi_heap.* *libheap.a:tlsf.* *liblog.a:log.* *liblog.a:log_format_text.* *liblog.a:log_lock.* *liblog.a:log_print.* *liblog.a:log_timestamp.* *liblog.a:log_timestamp_common.* *liblog.a:log_write.* *liblog.a:tag_log_level.* *liblog.a:util.* *libriscv.a:interrupt.* *libriscv.a:rv_utils.* *libriscv.a:vectors.* *libsoc.a:lldesc.* *libspi_flash.a:esp_flash_api.* *libspi_flash.a:flash_brownout_hook.* *libspi_flash.a:memspi_host_driver.* *libspi_flash.a:spi_flash_chip_boya.* *libspi_flash.a:spi_flash_chip_gd.* *libspi_flash.a:spi_flash_chip_generic.* *libspi_flash.a:spi_flash_chip_issi.* *libspi_flash.a:spi_flash_chip_mxic.* *libspi_flash.a:spi_flash_chip_th.* *libspi_flash.a:spi_flash_chip_winbond.* *libspi_flash.a:spi_flash_hpm_enable.* *libspi_flash.a:spi_flash_os_func_app.* *libspi_flash.a:spi_flash_os_func_noos.* *libspi_flash.a:spi_flash_wrap.*) .literal.* EXCLUDE_FILE(*libgcov.a *libclang_rt.builtins.a:_divsf3.* *libclang_rt.builtins.a:restore.* *libclang_rt.builtins.a:save.* *libesp_driver_dma.a:dma2d.* *libesp_driver_dma.a:dw_gdma.* *libesp_driver_dma.a:gdma.* *libesp_hal_dma.a:gdma_hal_ahb_v2.* *libesp_hal_dma.a:gdma_hal_axi.* *libesp_hal_dma.a:gdma_hal_top.* *libesp_hal_gpio.a:gpio_hal.* *libesp_hal_mspi.a:spi_flash_encrypt_hal_iram.* *libesp_hal_mspi.a:spi_flash_hal_gpspi.* *libesp_hal_mspi.a:spi_flash_hal_iram.* *libesp_hal_pmu.a:pmu_hal.* *libesp_hal_wdt.a:rom_patch.* *libesp_hw_support.a:clk_utils.* *libesp_hw_support.a:cpu.* *libesp_hw_support.a:esp_clk_tree.* *libesp_hw_support.a:esp_memory_utils.* *libesp_hw_support.a:mspi_timing_by_dqs.* *libesp_hw_support.a:mspi_timing_by_flash_delay.* *libesp_hw_support.a:mspi_timing_config.* *libesp_hw_support.a:mspi_timing_tuning.* *libesp_hw_support.a:periph_ctrl.* *libesp_hw_support.a:pmu_pvt.* *libesp_hw_support.a:pmu_sleep.* *libesp_hw_support.a:regi2c_ctrl.* *libesp_hw_support.a:rtc_clk.* *libesp_hw_support.a:rtc_time.* *libesp_hw_support.a:sleep_mspi.* *libesp_hw_support.a:systimer.* *libesp_libc.a:abort.* *libesp_libc.a:assert.* *libesp_libc.a:heap.* *libesp_libc.a:memcmp.* *libesp_libc.a:memcpy.* *libesp_libc.a:memmove.* *libesp_libc.a:stdatomic.* *libesp_libc.a:strcmp.* *libesp_libc.a:strcpy.* *libesp_libc.a:strncmp.* *libesp_libc.a:strncpy.* *libesp_mm.a:esp_cache_msync.* *libesp_mm.a:esp_cache_utils.* *libesp_rom.a:esp_rom_cache_writeback_esp32p4.* *libesp_rom.a:esp_rom_print.* *libesp_rom.a:esp_rom_spiflash.* *libesp_rom.a:esp_rom_sys.* *libesp_rom.a:esp_rom_systimer.* *libesp_system.a:esp_err.* *libesp_system.a:esp_system_chip.* *libesp_system.a:freertos_hooks.* *libesp_system.a:image_process.* *libesp_system.a:panic.* *libesp_system.a:reset_reason.* *libesp_system.a:system_internal.* *libesp_system.a:system_time.* *libesp_system.a:ubsan.* *libfreertos.a:event_groups.* *libfreertos.a:list.* *libfreertos.a:port.* *libfreertos.a:port_systick.* *libfreertos.a:portasm.* *libfreertos.a:queue.* *libfreertos.a:stream_buffer.* *libfreertos.a:tasks.* *libfreertos.a:timers.* *libgcc.a:_divsf3.* *libgcc.a:lib2funcs.* *libgcc.a:save-restore.* *libhal.a:cache_hal.* *libhal.a:mmu_hal.* *libheap.a:multi_heap.* *libheap.a:tlsf.* *liblog.a:log.* *liblog.a:log_format_text.* *liblog.a:log_lock.* *liblog.a:log_print.* *liblog.a:log_timestamp.* *liblog.a:log_timestamp_common.* *liblog.a:log_write.* *liblog.a:tag_log_level.* *liblog.a:util.* *libriscv.a:interrupt.* *libriscv.a:rv_utils.* *libriscv.a:vectors.* *libsoc.a:lldesc.* *libspi_flash.a:esp_flash_api.* *libspi_flash.a:flash_brownout_hook.* *libspi_flash.a:memspi_host_driver.* *libspi_flash.a:spi_flash_chip_boya.* *libspi_flash.a:spi_flash_chip_gd.* *libspi_flash.a:spi_flash_chip_generic.* *libspi_flash.a:spi_flash_chip_issi.* *libspi_flash.a:spi_flash_chip_mxic.* *libspi_flash.a:spi_flash_chip_th.* *libspi_flash.a:spi_flash_chip_winbond.* *libspi_flash.a:spi_flash_hpm_enable.* *libspi_flash.a:spi_flash_os_func_app.* *libspi_flash.a:spi_flash_os_func_noos.* *libspi_flash.a:spi_flash_wrap.*) .text EXCLUDE_FILE(*libgcov.a *libclang_rt.builtins.a:_divsf3.* *libclang_rt.builtins.a:restore.* *libclang_rt.builtins.a:save.* *libesp_driver_dma.a:dma2d.* *libesp_driver_dma.a:dw_gdma.* *libesp_driver_dma.a:gdma.* *libesp_hal_dma.a:gdma_hal_ahb_v2.* *libesp_hal_dma.a:gdma_hal_axi.* *libesp_hal_dma.a:gdma_hal_top.* *libesp_hal_gpio.a:gpio_hal.* *libesp_hal_mspi.a:spi_flash_encrypt_hal_iram.* *libesp_hal_mspi.a:spi_flash_hal_gpspi.* *libesp_hal_mspi.a:spi_flash_hal_iram.* *libesp_hal_pmu.a:pmu_hal.* *libesp_hal_wdt.a:rom_patch.* *libesp_hw_support.a:clk_utils.* *libesp_hw_support.a:cpu.* *libesp_hw_support.a:esp_clk_tree.* *libesp_hw_support.a:esp_memory_utils.* *libesp_hw_support.a:mspi_timing_by_dqs.* *libesp_hw_support.a:mspi_timing_by_flash_delay.* *libesp_hw_support.a:mspi_timing_config.* *libesp_hw_support.a:mspi_timing_tuning.* *libesp_hw_support.a:periph_ctrl.* *libesp_hw_support.a:pmu_pvt.* *libesp_hw_support.a:pmu_sleep.* *libesp_hw_support.a:regi2c_ctrl.* *libesp_hw_support.a:rtc_clk.* *libesp_hw_support.a:rtc_time.* *libesp_hw_support.a:sleep_mspi.* *libesp_hw_support.a:systimer.* *libesp_libc.a:abort.* *libesp_libc.a:assert.* *libesp_libc.a:heap.* *libesp_libc.a:memcmp.* *libesp_libc.a:memcpy.* *libesp_libc.a:memmove.* *libesp_libc.a:stdatomic.* *libesp_libc.a:strcmp.* *libesp_libc.a:strcpy.* *libesp_libc.a:strncmp.* *libesp_libc.a:strncpy.* *libesp_mm.a:esp_cache_msync.* *libesp_mm.a:esp_cache_utils.* *libesp_rom.a:esp_rom_cache_writeback_esp32p4.* *libesp_rom.a:esp_rom_print.* *libesp_rom.a:esp_rom_spiflash.* *libesp_rom.a:esp_rom_sys.* *libesp_rom.a:esp_rom_systimer.* *libesp_system.a:esp_err.* *libesp_system.a:esp_system_chip.* *libesp_system.a:freertos_hooks.* *libesp_system.a:image_process.* *libesp_system.a:panic.* *libesp_system.a:reset_reason.* *libesp_system.a:system_internal.* *libesp_system.a:system_time.* *libesp_system.a:ubsan.* *libfreertos.a:event_groups.* *libfreertos.a:list.* *libfreertos.a:port.* *libfreertos.a:port_systick.* *libfreertos.a:portasm.* *libfreertos.a:queue.* *libfreertos.a:stream_buffer.* *libfreertos.a:tasks.* *libfreertos.a:timers.* *libgcc.a:_divsf3.* *libgcc.a:lib2funcs.* *libgcc.a:save-restore.* *libhal.a:cache_hal.* *libhal.a:mmu_hal.* *libheap.a:multi_heap.* *libheap.a:tlsf.* *liblog.a:log.* *liblog.a:log_format_text.* *liblog.a:log_lock.* *liblog.a:log_print.* *liblog.a:log_timestamp.* *liblog.a:log_timestamp_common.* *liblog.a:log_write.* *liblog.a:tag_log_level.* *liblog.a:util.* *libriscv.a:interrupt.* *libriscv.a:rv_utils.* *libriscv.a:vectors.* *libsoc.a:lldesc.* *libspi_flash.a:esp_flash_api.* *libspi_flash.a:flash_brownout_hook.* *libspi_flash.a:memspi_host_driver.* *libspi_flash.a:spi_flash_chip_boya.* *libspi_flash.a:spi_flash_chip_gd.* *libspi_flash.a:spi_flash_chip_generic.* *libspi_flash.a:spi_flash_chip_issi.* *libspi_flash.a:spi_flash_chip_mxic.* *libspi_flash.a:spi_flash_chip_th.* *libspi_flash.a:spi_flash_chip_winbond.* *libspi_flash.a:spi_flash_hpm_enable.* *libspi_flash.a:spi_flash_os_func_app.* *libspi_flash.a:spi_flash_os_func_noos.* *libspi_flash.a:spi_flash_wrap.*) .text.*)
 *libesp_driver_dma.a:dma2d.*(.text .text.dma2d_acquire_pool .text.dma2d_append .text.dma2d_apply_strategy .text.dma2d_configure_color_space_conversion .text.dma2d_configure_dscr_port_mode .text.dma2d_connect .text.dma2d_dequeue .text.dma2d_enqueue .text.dma2d_force_end .text.dma2d_get_trans_elm_size .text.dma2d_register_rx_event_callbacks .text.dma2d_register_tx_event_callbacks .text.dma2d_release_pool .text.dma2d_reset .text.dma2d_set_desc_addr .text.dma2d_set_transfer_ability .text.dma2d_start .text.dma2d_stop)
 *libesp_driver_dma.a:dw_gdma.*(.text .text.channel_destroy .text.channel_register_to_group .text.channel_unregister_from_group .text.dw_gdma_acquire_group_handle .text.dw_gdma_channel_abort .text.dw_gdma_channel_config_transfer .text.dw_gdma_channel_continue .text.dw_gdma_channel_enable_ctrl .text.dw_gdma_channel_get_id .text.dw_gdma_channel_lock .text.dw_gdma_channel_register_event_callbacks .text.dw_gdma_channel_set_block_markers .text.dw_gdma_channel_suspend_ctrl .text.dw_gdma_channel_unlock .text.dw_gdma_channel_use_link_list .text.dw_gdma_del_channel .text.dw_gdma_del_link_list .text.dw_gdma_install_channel_interrupt .text.dw_gdma_link_list_get_item .text.dw_gdma_ll_channel_set_dst_handshake_periph .text.dw_gdma_ll_channel_set_src_handshake_periph .text.dw_gdma_ll_channel_set_trans_flow .text.dw_gdma_lli_config_transfer .text.dw_gdma_lli_set_block_markers .text.dw_gdma_lli_set_next .text.dw_gdma_new_channel .text.dw_gdma_new_link_list .text.dw_gdma_release_group_handle)
 *libesp_driver_dma.a:gdma.*(.text .text.do_allocate_gdma_channel .text.gdma_append .text.gdma_apply_strategy .text.gdma_config_transfer .text.gdma_connect .text.gdma_del_channel .text.gdma_del_rx_channel .text.gdma_del_tx_channel .text.gdma_disconnect .text.gdma_get_alignment_constraints .text.gdma_get_free_m2m_trig_id_mask .text.gdma_get_group_channel_id .text.gdma_install_rx_interrupt .text.gdma_install_tx_interrupt .text.gdma_new_ahb_channel .text.gdma_new_axi_channel .text.gdma_register_rx_event_callbacks .text.gdma_register_tx_event_callbacks .text.gdma_request_link_switch_event .text.gdma_reset .text.gdma_set_priority .text.gdma_start .text.gdma_stop .text.gdma_try_alloc_group_handle .text.gdma_try_alloc_pair_handle .text.gdma_try_free_group_handle .text.gdma_try_free_pair_handle)
 *libesp_hal_dma.a:gdma_hal_ahb_v2.*(.text .text.ahb_dma_ll_rx_crc_set_lfsr_data_mask .text.ahb_dma_ll_rx_crc_set_width .text.ahb_dma_ll_rx_set_burst_size .text.ahb_dma_ll_tx_crc_set_lfsr_data_mask .text.ahb_dma_ll_tx_crc_set_width .text.ahb_dma_ll_tx_set_burst_size .text.gdma_ahb_hal_append .text.gdma_ahb_hal_clear_crc .text.gdma_ahb_hal_connect_mem .text.gdma_ahb_hal_connect_peri .text.gdma_ahb_hal_disconnect_all .text.gdma_ahb_hal_enable_burst .text.gdma_ahb_hal_enable_etm_task .text.gdma_ahb_hal_enable_intr .text.gdma_ahb_hal_get_crc_result .text.gdma_ahb_hal_get_intr_status_reg .text.gdma_ahb_hal_init .text.gdma_ahb_hal_reset .text.gdma_ahb_hal_set_burst_size .text.gdma_ahb_hal_set_crc_poly .text.gdma_ahb_hal_set_priority .text.gdma_ahb_hal_set_strategy .text.gdma_ahb_hal_start_with_desc .text.gdma_ahb_hal_stop)
 *libesp_hal_dma.a:gdma_hal_axi.*(.text .text.axi_dma_ll_rx_crc_set_lfsr_data_mask .text.axi_dma_ll_rx_crc_set_width .text.axi_dma_ll_rx_set_burst_size .text.axi_dma_ll_tx_crc_set_lfsr_data_mask .text.axi_dma_ll_tx_crc_set_width .text.axi_dma_ll_tx_request_link_switch_event .text.axi_dma_ll_tx_set_burst_size .text.gdma_axi_hal_append .text.gdma_axi_hal_clear_crc .text.gdma_axi_hal_connect_mem .text.gdma_axi_hal_connect_peri .text.gdma_axi_hal_disconnect_all .text.gdma_axi_hal_enable_burst .text.gdma_axi_hal_enable_etm_task .text.gdma_axi_hal_enable_intr .text.gdma_axi_hal_get_crc_result .text.gdma_axi_hal_get_intr_status_reg .text.gdma_axi_hal_init .text.gdma_axi_hal_request_link_switch_event .text.gdma_axi_hal_reset .text.gdma_axi_hal_set_burst_size .text.gdma_axi_hal_set_crc_poly .text.gdma_axi_hal_set_priority .text.gdma_axi_hal_set_strategy .text.gdma_axi_hal_start_with_desc .text.gdma_axi_hal_stop)
 *libesp_hal_dma.a:gdma_hal_top.*(.text .text.gdma_hal_append .text.gdma_hal_clear_crc .text.gdma_hal_connect_mem .text.gdma_hal_connect_peri .text.gdma_hal_deinit .text.gdma_hal_disconnect_all .text.gdma_hal_enable_burst .text.gdma_hal_enable_etm_task .text.gdma_hal_enable_intr .text.gdma_hal_get_crc_result .text.gdma_hal_get_intr_status_reg .text.gdma_hal_request_link_switch_event .text.gdma_hal_reset .text.gdma_hal_set_burst_size .text.gdma_hal_set_crc_poly .text.gdma_hal_set_priority .text.gdma_hal_set_strategy .text.gdma_hal_start_with_desc .text.gdma_hal_stop)
 *libesp_hal_gpio.a:gpio_hal.*(.text .text.gpio_hal_hysteresis_soft_enable .text.gpio_hal_intr_disable .text.gpio_hal_intr_enable_on_core .text.gpio_hal_iomux_in .text.gpio_hal_iomux_out .text.gpio_hal_matrix_in .text.gpio_hal_matrix_out .text.gpio_ll_pin_input_hysteresis_disable .text.gpio_ll_pin_input_hysteresis_enable)
 *libesp_hw_support.a:cpu.*(.text .text.esp_cpu_clear_breakpoint .text.esp_cpu_clear_watchpoint .text.esp_cpu_set_breakpoint .text.esp_cpu_set_watchpoint)
 *libesp_hw_support.a:esp_clk_tree.*(.text .text.esp_clk_tree_initialize .text.esp_clk_tree_src_get_freq_hz .text.esp_clk_tree_src_set_freq_hz)
 *libesp_hw_support.a:periph_ctrl.*(.text .text.periph_module_disable .text.periph_module_enable)
 *libesp_hw_support.a:regi2c_ctrl.*(.text .text.regi2c_ctrl_ll_i2c_sar_periph_enable .text.regi2c_saradc_disable .text.regi2c_saradc_enable)
 *libesp_system.a:esp_system_chip.*(.text .text.esp_get_free_heap_size .text.esp_get_free_internal_heap_size .text.esp_get_idf_version .text.esp_get_minimum_free_heap_size)
 *libesp_system.a:freertos_hooks.*(.text .text.esp_deregister_freertos_idle_hook .text.esp_deregister_freertos_idle_hook_for_cpu .text.esp_deregister_freertos_tick_hook .text.esp_deregister_freertos_tick_hook_for_cpu .text.esp_register_freertos_idle_hook .text.esp_register_freertos_idle_hook_for_cpu .text.esp_register_freertos_tick_hook .text.esp_register_freertos_tick_hook_for_cpu .text.esp_vApplicationIdleHook)
 *libesp_system.a:panic.*(.text .text.disable_all_wdts .text.esp_panic_handler .text.esp_panic_handler_disable_timg_wdts .text.esp_panic_handler_enable_rtc_wdt .text.esp_panic_handler_feed_wdts .text.esp_panic_handler_increment_entry_count .text.esp_reset_reason_get_hint .text.esp_reset_reason_set_hint .text.panic_print_char .text.panic_print_char_uart .text.panic_print_char_usb_serial_jtag .text.panic_print_dec .text.panic_print_hex .text.panic_print_str .text.print_abort_details .text.semihosting_call_noerrno)
 *libesp_system.a:reset_reason.*(.text .text.esp_reset_reason .text.esp_reset_reason_get_hint .text.esp_reset_reason_init .text.get_reset_reason)
 *libesp_system.a:system_internal.*(.text)
 *libesp_system.a:system_time.*(.text)
 *libfreertos.a:event_groups.*(.text .text.prvTestWaitCondition .text.vEventGroupClearBitsCallback .text.vEventGroupDelete .text.vEventGroupSetBitsCallback .text.xEventGroupClearBits .text.xEventGroupCreate .text.xEventGroupCreateStatic .text.xEventGroupGetStaticBuffer .text.xEventGroupSetBits .text.xEventGroupSync .text.xEventGroupWaitBits)
 *libfreertos.a:list.*(.text .text.vListInitialise .text.vListInitialiseItem .text.vListInsert)
 *libfreertos.a:port.*(.text .text.Atomic_CompareAndSwapPointers_p32 .text.pxPortGetCoprocArea .text.pxPortInitialiseStack .text.pxPortUpdateCoprocOwner .text.vApplicationStackOverflowHook .text.vPortCleanUpCoprocArea .text.vPortEndScheduler .text.vPortExitCriticalCompliance .text.vPortTCBPreDeleteHook .text.vPortTLSPointersDelCb .text.vPortTaskPinToCore .text.vPortTaskWrapper .text.xPortEnterCriticalTimeoutCompliance .text.xPortGetTickRateHz .text.xPortStartScheduler)
 *libfreertos.a:port_systick.*(.literal.vPortSetupTimer .text.vPortSetupTimer)
 *libfreertos.a:port_systick.*(.literal.vSystimerSetup .text.vSystimerSetup)
 *libfreertos.a:queue.*(.text .text.prvGetDisinheritPriorityAfterTimeout .text.prvInitialiseMutex .text.prvInitialiseNewQueue .text.uxQueueMessagesWaiting .text.uxQueueSpacesAvailable .text.vQueueDelete .text.vQueueWaitForMessageRestricted .text.xQueueAddToSet .text.xQueueCreateCountingSemaphore .text.xQueueCreateCountingSemaphoreStatic .text.xQueueCreateMutex .text.xQueueCreateMutexStatic .text.xQueueCreateSet .text.xQueueGenericCreate .text.xQueueGenericCreateStatic .text.xQueueGenericGetStaticBuffers .text.xQueueGenericReset .text.xQueueGenericSend .text.xQueueGetMutexHolder .text.xQueueGiveMutexRecursive .text.xQueuePeek .text.xQueueReceive .text.xQueueRemoveFromSet .text.xQueueSelectFromSet .text.xQueueSemaphoreTake .text.xQueueTakeMutexRecursive)
 *libfreertos.a:stream_buffer.*(.text .text.prvInitialiseNewStreamBuffer .text.prvReadBytesFromBuffer .text.prvWriteBytesToBuffer .text.vStreamBufferDelete .text.xStreamBufferBytesAvailable .text.xStreamBufferGenericCreate .text.xStreamBufferGenericCreateStatic .text.xStreamBufferGetStaticBuffers .text.xStreamBufferIsEmpty .text.xStreamBufferIsFull .text.xStreamBufferNextMessageLengthBytes .text.xStreamBufferReceive .text.xStreamBufferReset .text.xStreamBufferSend .text.xStreamBufferSetTriggerLevel .text.xStreamBufferSpacesAvailable)
 *libfreertos.a:tasks.*(.text .text.eTaskGetState .text.pcTaskGetName .text.prvAddCurrentTaskToDelayedList .text.prvAddNewTaskToReadyList .text.prvCheckTasksWaitingTermination .text.prvCreateIdleTasks .text.prvDeleteTCB .text.prvIdleTask .text.prvInitialiseNewTask .text.prvInitialiseTaskLists .text.prvReleaseKernelLock .text.prvSearchForNameWithinSingleList .text.prvTakeKernelLock .text.prvTaskCheckFreeStackSpace .text.prvTaskPriorityRaise .text.prvTaskPriorityRestore .text.pvTaskGetCurrentTCBForCore .text.pvTaskGetThreadLocalStoragePointer .text.pvTaskIncrementMutexHeldCount .text.pxGetTaskListByIndex .text.pxTaskGetStackStart .text.ulTaskGenericNotifyTake .text.ulTaskGenericNotifyValueClear .text.uxTaskGetNumberOfTasks .text.uxTaskGetSnapshotAll .text.uxTaskGetStackHighWaterMark .text.uxTaskGetStackHighWaterMark2 .text.uxTaskPriorityGet .text.uxTaskResetEventItemValue .text.vTaskDelay .text.vTaskDelete .text.vTaskEndScheduler .text.vTaskInternalSetTimeOutState .text.vTaskMissedYield .text.vTaskPlaceOnEventList .text.vTaskPlaceOnEventListRestricted .text.vTaskPlaceOnUnorderedEventList .text.vTaskPriorityDisinheritAfterTimeout .text.vTaskPrioritySet .text.vTaskRemoveFromUnorderedEventList .text.vTaskResume .text.vTaskSetThreadLocalStoragePointer .text.vTaskSetThreadLocalStoragePointerAndDelCallback .text.vTaskSetTimeOutState .text.vTaskStartScheduler .text.vTaskSuspend .text.vTaskSuspendAll .text.xTaskAbortDelay .text.xTaskCatchUpTicks .text.xTaskCheckForTimeOut .text.xTaskCreatePinnedToCore .text.xTaskCreateStaticPinnedToCore .text.xTaskDelayUntil .text.xTaskGenericNotify .text.xTaskGenericNotifyStateClear .text.xTaskGenericNotifyWait .text.xTaskGetCoreID .text.xTaskGetCurrentTaskHandle .text.xTaskGetCurrentTaskHandleForCore .text.xTaskGetHandle .text.xTaskGetIdleTaskHandle .text.xTaskGetIdleTaskHandleForCore .text.xTaskGetNext .text.xTaskGetStackStart .text.xTaskGetStaticBuffers .text.xTaskPriorityDisinherit .text.xTaskPriorityInherit .text.xTaskResumeAll .text.xTimerCreateTimerTask)
 *libfreertos.a:timers.*(.text .text.pcTimerGetName .text.prvCheckForValidListAndQueue .text.prvGetNextExpireTime .text.prvInitialiseNewTimer .text.prvInsertTimerInActiveList .text.prvProcessExpiredTimer .text.prvProcessReceivedCommands .text.prvProcessTimerOrBlockTask .text.prvReloadTimer .text.prvSampleTimeNow .text.prvSwitchTimerLists .text.prvTimerTask .text.pvTimerGetTimerID .text.uxTimerGetReloadMode .text.vTimerSetReloadMode .text.vTimerSetTimerID .text.xTimerCreate .text.xTimerCreateStatic .text.xTimerCreateTimerTask .text.xTimerGetExpiryTime .text.xTimerGetPeriod .text.xTimerGetReloadMode .text.xTimerGetStaticBuffer .text.xTimerGetTimerDaemonTaskHandle .text.xTimerIsTimerActive .text.xTimerPendFunctionCall)
 *libheap.a:multi_heap.*(.text .text.multi_heap_check .text.multi_heap_dump .text.multi_heap_dump_tlsf .text.multi_heap_find_containing_block_impl .text.multi_heap_free_size_impl .text.multi_heap_get_info_impl .text.multi_heap_get_info_tlsf .text.multi_heap_minimum_free_size_impl .text.multi_heap_register_impl .text.multi_heap_reset_minimum_free_bytes .text.multi_heap_restore_minimum_free_bytes .text.multi_heap_walk)
 *libheap.a:tlsf.*(.text .text.control_construct .text.default_walker .text.integrity_walker .text.tlsf_add_pool .text.tlsf_check .text.tlsf_check_pool .text.tlsf_create .text.tlsf_create_with_pool .text.tlsf_destroy .text.tlsf_find_containing_block .text.tlsf_fit_size .text.tlsf_malloc_addr .text.tlsf_pool_overhead .text.tlsf_remove_pool .text.tlsf_walk_pool)
 *liblog.a:log_timestamp.*(.text)
 *liblog.a:log_write.*(.text .text.esp_log_set_vprintf)
 *liblog.a:tag_log_level.*(.text .text.esp_log_level_get .text.esp_log_level_set .text.log_level_get .text.log_level_set)
 *libriscv.a:interrupt.*(.literal.intr_handler_get .text.intr_handler_get)
 *libriscv.a:interrupt.*(.literal.intr_handler_set .text.intr_handler_set)
 *libspi_flash.a:esp_flash_api.*(.text .text.esp_flash_app_disable_protect .text.esp_flash_get_protectable_regions .text.esp_flash_read_chip_id .text.esp_flash_read_id .text.esp_flash_read_unique_chip_id .text.esp_flash_suspend_cmd_init .text.find_region)
 *libspi_flash.a:spi_flash_os_func_app.*(.text .text.esp_flash_app_enable_os_functions .text.esp_flash_deinit_os_functions .text.esp_flash_init_main_bus_lock .text.esp_flash_init_os_functions .text.esp_flash_set_dangerous_write_protection .text.use_bus_lock)
 *libspi_flash.a:spi_flash_os_func_noos.*(.text)
 mutable[flash_text]
    *(.stub)
    *(.gnu.linkonce.t.*)
    *(.gnu.warning)
    *(.irom0.text) /* catch stray ICACHE_RODATA_ATTR */
    /**
     * CPU will try to prefetch up to 16 bytes of instructions.
     * This means that any configuration (e.g. MMU, PMS) must allow
     * safe access to up to 16 bytes after the last real instruction.
     * Add dummy bytes to ensure this.
     */
    . += 16;
    _text_end = ABSOLUTE(.);
    /**
     * Mark the flash.text end.
     * This can be used for MMU driver to maintain virtual address.
     */
    _instruction_reserved_end = ABSOLUTE(.);
    _etext = .;
    /**
     * Similar to _iram_start, this symbol goes here so it is
     * resolved by addr2line in preference to the first symbol in
     * the flash.text segment.
     */
    _flash_cache_start = ABSOLUTE(0);
  } > flash_text_seg
  /**
   * Dummy section represents the .flash.text section but in flash_rodata_seg.
   * Thus, it must have its alignment and (at least) its size.
   */
  .flash_rodata_dummy (NOLOAD) :
  {
    _flash_rodata_dummy_start = .;
    . = ALIGN(ALIGNOF(.flash.text)) + SIZEOF(.flash.text);
    /* Add alignment of MMU page size + 0x20 bytes for the mapping header */
    . = ALIGN(0x10000) + 0x20;
  } > flash_rodata_seg
  .flash.appdesc : ALIGN(0x10)
  {
    /**
     * Mark flash.rodata start.
     * This can be used for MMU driver to maintain virtual address.
     */
    _rodata_reserved_start = ABSOLUTE(.);
    _rodata_start = ABSOLUTE(.);
    /* !DO NOT PUT ANYTHING BEFORE THIS! */
    /* Should be the first: App version info */
    *(.rodata_desc .rodata_desc.*)
    /* Should be the second: Custom app version info */
    *(.rodata_custom_desc .rodata_custom_desc.*)
    /**
     * Create an empty gap within this section. Thanks to this, the end of this
     * section will match .flash.rodata's begin address. Thus, both sections
     * will be merged when creating the final bin image.
     */
    . = ALIGN(ALIGNOF(.flash.rodata));
  } > flash_rodata_seg
  ASSERT((ADDR(.flash.rodata) == ADDR(.flash.appdesc) + SIZEOF(.flash.appdesc)), "The gap between .flash.appdesc and .flash.rodata must not exist to produce the final bin image.")
  .flash.rodata : ALIGN(0x10)
  {
    _flash_rodata_start = ABSOLUTE(.);
    
 *(EXCLUDE_FILE(*libgcov.a *libclang_rt.builtins.a:_divsf3.* *libclang_rt.builtins.a:restore.* *libclang_rt.builtins.a:save.* *libesp_driver_dma.a:dma2d.* *libesp_hal_mspi.a:spi_flash_encrypt_hal_iram.* *libesp_hal_mspi.a:spi_flash_hal_gpspi.* *libesp_hal_mspi.a:spi_flash_hal_iram.* *libesp_hal_pmu.a:pmu_hal.* *libesp_hal_wdt.a:rom_patch.* *libesp_hw_support.a:clk_utils.* *libesp_hw_support.a:cpu.* *libesp_hw_support.a:esp_clk_tree.* *libesp_hw_support.a:esp_memory_utils.* *libesp_hw_support.a:mspi_timing_by_dqs.* *libesp_hw_support.a:mspi_timing_by_flash_delay.* *libesp_hw_support.a:mspi_timing_config.* *libesp_hw_support.a:mspi_timing_tuning.* *libesp_hw_support.a:pmu_pvt.* *libesp_hw_support.a:pmu_sleep.* *libesp_hw_support.a:rtc_clk.* *libesp_hw_support.a:sleep_mspi.* *libesp_hw_support.a:systimer.* *libesp_libc.a:abort.* *libesp_libc.a:assert.* *libesp_libc.a:heap.* *libesp_libc.a:memcmp.* *libesp_libc.a:memcpy.* *libesp_libc.a:memmove.* *libesp_libc.a:stdatomic.* *libesp_libc.a:strcmp.* *libesp_libc.a:strcpy.* *libesp_libc.a:strncmp.* *libesp_libc.a:strncpy.* *libesp_mm.a:esp_cache_msync.* *libesp_mm.a:esp_cache_utils.* *libesp_rom.a:esp_rom_cache_writeback_esp32p4.* *libesp_rom.a:esp_rom_print.* *libesp_rom.a:esp_rom_spiflash.* *libesp_rom.a:esp_rom_sys.* *libesp_rom.a:esp_rom_systimer.* *libesp_system.a:esp_err.* *libesp_system.a:image_process.* *libesp_system.a:reset_reason.* *libesp_system.a:system_internal.* *libesp_system.a:ubsan.* *libgcc.a:_divsf3.* *libgcc.a:save-restore.* *libhal.a:cache_hal.* *libhal.a:mmu_hal.* *libheap.a:multi_heap.* *libheap.a:tlsf.* *liblog.a:log.* *liblog.a:log_format_text.* *liblog.a:log_lock.* *liblog.a:log_print.* *liblog.a:log_timestamp_common.* *liblog.a:util.* *libsoc.a:lldesc.* *libspi_flash.a:flash_brownout_hook.* *libspi_flash.a:memspi_host_driver.* *libspi_flash.a:spi_flash_chip_boya.* *libspi_flash.a:spi_flash_chip_gd.* *libspi_flash.a:spi_flash_chip_generic.* *libspi_flash.a:spi_flash_chip_issi.* *libspi_flash.a:spi_flash_chip_mxic.* *libspi_flash.a:spi_flash_chip_th.* *libspi_flash.a:spi_flash_chip_winbond.* *libspi_flash.a:spi_flash_hpm_enable.* *libspi_flash.a:spi_flash_os_func_app.* *libspi_flash.a:spi_flash_wrap.*) .rodata EXCLUDE_FILE(*libgcov.a *libclang_rt.builtins.a:_divsf3.* *libclang_rt.builtins.a:restore.* *libclang_rt.builtins.a:save.* *libesp_driver_dma.a:dma2d.* *libesp_hal_mspi.a:spi_flash_encrypt_hal_iram.* *libesp_hal_mspi.a:spi_flash_hal_gpspi.* *libesp_hal_mspi.a:spi_flash_hal_iram.* *libesp_hal_pmu.a:pmu_hal.* *libesp_hal_wdt.a:rom_patch.* *libesp_hw_support.a:clk_utils.* *libesp_hw_support.a:cpu.* *libesp_hw_support.a:esp_clk_tree.* *libesp_hw_support.a:esp_memory_utils.* *libesp_hw_support.a:mspi_timing_by_dqs.* *libesp_hw_support.a:mspi_timing_by_flash_delay.* *libesp_hw_support.a:mspi_timing_config.* *libesp_hw_support.a:mspi_timing_tuning.* *libesp_hw_support.a:pmu_pvt.* *libesp_hw_support.a:pmu_sleep.* *libesp_hw_support.a:rtc_clk.* *libesp_hw_support.a:sleep_mspi.* *libesp_hw_support.a:systimer.* *libesp_libc.a:abort.* *libesp_libc.a:assert.* *libesp_libc.a:heap.* *libesp_libc.a:memcmp.* *libesp_libc.a:memcpy.* *libesp_libc.a:memmove.* *libesp_libc.a:stdatomic.* *libesp_libc.a:strcmp.* *libesp_libc.a:strcpy.* *libesp_libc.a:strncmp.* *libesp_libc.a:strncpy.* *libesp_mm.a:esp_cache_msync.* *libesp_mm.a:esp_cache_utils.* *libesp_rom.a:esp_rom_cache_writeback_esp32p4.* *libesp_rom.a:esp_rom_print.* *libesp_rom.a:esp_rom_spiflash.* *libesp_rom.a:esp_rom_sys.* *libesp_rom.a:esp_rom_systimer.* *libesp_system.a:esp_err.* *libesp_system.a:image_process.* *libesp_system.a:reset_reason.* *libesp_system.a:system_internal.* *libesp_system.a:ubsan.* *libgcc.a:_divsf3.* *libgcc.a:save-restore.* *libhal.a:cache_hal.* *libhal.a:mmu_hal.* *libheap.a:multi_heap.* *libheap.a:tlsf.* *liblog.a:log.* *liblog.a:log_format_text.* *liblog.a:log_lock.* *liblog.a:log_print.* *liblog.a:log_timestamp_common.* *liblog.a:util.* *libsoc.a:lldesc.* *libspi_flash.a:flash_brownout_hook.* *libspi_flash.a:memspi_host_driver.* *libspi_flash.a:spi_flash_chip_boya.* *libspi_flash.a:spi_flash_chip_gd.* *libspi_flash.a:spi_flash_chip_generic.* *libspi_flash.a:spi_flash_chip_issi.* *libspi_flash.a:spi_flash_chip_mxic.* *libspi_flash.a:spi_flash_chip_th.* *libspi_flash.a:spi_flash_chip_winbond.* *libspi_flash.a:spi_flash_hpm_enable.* *libspi_flash.a:spi_flash_os_func_app.* *libspi_flash.a:spi_flash_wrap.*) .rodata.* EXCLUDE_FILE(*libgcov.a *libclang_rt.builtins.a:_divsf3.* *libclang_rt.builtins.a:restore.* *libclang_rt.builtins.a:save.* *libesp_driver_dma.a:dma2d.* *libesp_hal_mspi.a:spi_flash_encrypt_hal_iram.* *libesp_hal_mspi.a:spi_flash_hal_gpspi.* *libesp_hal_mspi.a:spi_flash_hal_iram.* *libesp_hal_pmu.a:pmu_hal.* *libesp_hal_wdt.a:rom_patch.* *libesp_hw_support.a:clk_utils.* *libesp_hw_support.a:cpu.* *libesp_hw_support.a:esp_clk_tree.* *libesp_hw_support.a:esp_memory_utils.* *libesp_hw_support.a:mspi_timing_by_dqs.* *libesp_hw_support.a:mspi_timing_by_flash_delay.* *libesp_hw_support.a:mspi_timing_config.* *libesp_hw_support.a:mspi_timing_tuning.* *libesp_hw_support.a:pmu_pvt.* *libesp_hw_support.a:pmu_sleep.* *libesp_hw_support.a:rtc_clk.* *libesp_hw_support.a:sleep_mspi.* *libesp_hw_support.a:systimer.* *libesp_libc.a:abort.* *libesp_libc.a:assert.* *libesp_libc.a:heap.* *libesp_libc.a:memcmp.* *libesp_libc.a:memcpy.* *libesp_libc.a:memmove.* *libesp_libc.a:stdatomic.* *libesp_libc.a:strcmp.* *libesp_libc.a:strcpy.* *libesp_libc.a:strncmp.* *libesp_libc.a:strncpy.* *libesp_mm.a:esp_cache_msync.* *libesp_mm.a:esp_cache_utils.* *libesp_rom.a:esp_rom_cache_writeback_esp32p4.* *libesp_rom.a:esp_rom_print.* *libesp_rom.a:esp_rom_spiflash.* *libesp_rom.a:esp_rom_sys.* *libesp_rom.a:esp_rom_systimer.* *libesp_system.a:esp_err.* *libesp_system.a:image_process.* *libesp_system.a:reset_reason.* *libesp_system.a:system_internal.* *libesp_system.a:ubsan.* *libgcc.a:_divsf3.* *libgcc.a:save-restore.* *libhal.a:cache_hal.* *libhal.a:mmu_hal.* *libheap.a:multi_heap.* *libheap.a:tlsf.* *liblog.a:log.* *liblog.a:log_format_text.* *liblog.a:log_lock.* *liblog.a:log_print.* *liblog.a:log_timestamp_common.* *liblog.a:util.* *libsoc.a:lldesc.* *libspi_flash.a:flash_brownout_hook.* *libspi_flash.a:memspi_host_driver.* *libspi_flash.a:spi_flash_chip_boya.* *libspi_flash.a:spi_flash_chip_gd.* *libspi_flash.a:spi_flash_chip_generic.* *libspi_flash.a:spi_flash_chip_issi.* *libspi_flash.a:spi_flash_chip_mxic.* *libspi_flash.a:spi_flash_chip_th.* *libspi_flash.a:spi_flash_chip_winbond.* *libspi_flash.a:spi_flash_hpm_enable.* *libspi_flash.a:spi_flash_os_func_app.* *libspi_flash.a:spi_flash_wrap.*) .sdata2 EXCLUDE_FILE(*libgcov.a *libclang_rt.builtins.a:_divsf3.* *libclang_rt.builtins.a:restore.* *libclang_rt.builtins.a:save.* *libesp_driver_dma.a:dma2d.* *libesp_hal_mspi.a:spi_flash_encrypt_hal_iram.* *libesp_hal_mspi.a:spi_flash_hal_gpspi.* *libesp_hal_mspi.a:spi_flash_hal_iram.* *libesp_hal_pmu.a:pmu_hal.* *libesp_hal_wdt.a:rom_patch.* *libesp_hw_support.a:clk_utils.* *libesp_hw_support.a:cpu.* *libesp_hw_support.a:esp_clk_tree.* *libesp_hw_support.a:esp_memory_utils.* *libesp_hw_support.a:mspi_timing_by_dqs.* *libesp_hw_support.a:mspi_timing_by_flash_delay.* *libesp_hw_support.a:mspi_timing_config.* *libesp_hw_support.a:mspi_timing_tuning.* *libesp_hw_support.a:pmu_pvt.* *libesp_hw_support.a:pmu_sleep.* *libesp_hw_support.a:rtc_clk.* *libesp_hw_support.a:sleep_mspi.* *libesp_hw_support.a:systimer.* *libesp_libc.a:abort.* *libesp_libc.a:assert.* *libesp_libc.a:heap.* *libesp_libc.a:memcmp.* *libesp_libc.a:memcpy.* *libesp_libc.a:memmove.* *libesp_libc.a:stdatomic.* *libesp_libc.a:strcmp.* *libesp_libc.a:strcpy.* *libesp_libc.a:strncmp.* *libesp_libc.a:strncpy.* *libesp_mm.a:esp_cache_msync.* *libesp_mm.a:esp_cache_utils.* *libesp_rom.a:esp_rom_cache_writeback_esp32p4.* *libesp_rom.a:esp_rom_print.* *libesp_rom.a:esp_rom_spiflash.* *libesp_rom.a:esp_rom_sys.* *libesp_rom.a:esp_rom_systimer.* *libesp_system.a:esp_err.* *libesp_system.a:image_process.* *libesp_system.a:reset_reason.* *libesp_system.a:system_internal.* *libesp_system.a:ubsan.* *libgcc.a:_divsf3.* *libgcc.a:save-restore.* *libhal.a:cache_hal.* *libhal.a:mmu_hal.* *libheap.a:multi_heap.* *libheap.a:tlsf.* *liblog.a:log.* *liblog.a:log_format_text.* *liblog.a:log_lock.* *liblog.a:log_print.* *liblog.a:log_timestamp_common.* *liblog.a:util.* *libsoc.a:lldesc.* *libspi_flash.a:flash_brownout_hook.* *libspi_flash.a:memspi_host_driver.* *libspi_flash.a:spi_flash_chip_boya.* *libspi_flash.a:spi_flash_chip_gd.* *libspi_flash.a:spi_flash_chip_generic.* *libspi_flash.a:spi_flash_chip_issi.* *libspi_flash.a:spi_flash_chip_mxic.* *libspi_flash.a:spi_flash_chip_th.* *libspi_flash.a:spi_flash_chip_winbond.* *libspi_flash.a:spi_flash_hpm_enable.* *libspi_flash.a:spi_flash_os_func_app.* *libspi_flash.a:spi_flash_wrap.*) .sdata2.* EXCLUDE_FILE(*libgcov.a *libclang_rt.builtins.a:_divsf3.* *libclang_rt.builtins.a:restore.* *libclang_rt.builtins.a:save.* *libesp_driver_dma.a:dma2d.* *libesp_hal_mspi.a:spi_flash_encrypt_hal_iram.* *libesp_hal_mspi.a:spi_flash_hal_gpspi.* *libesp_hal_mspi.a:spi_flash_hal_iram.* *libesp_hal_pmu.a:pmu_hal.* *libesp_hal_wdt.a:rom_patch.* *libesp_hw_support.a:clk_utils.* *libesp_hw_support.a:cpu.* *libesp_hw_support.a:esp_clk_tree.* *libesp_hw_support.a:esp_memory_utils.* *libesp_hw_support.a:mspi_timing_by_dqs.* *libesp_hw_support.a:mspi_timing_by_flash_delay.* *libesp_hw_support.a:mspi_timing_config.* *libesp_hw_support.a:mspi_timing_tuning.* *libesp_hw_support.a:pmu_pvt.* *libesp_hw_support.a:pmu_sleep.* *libesp_hw_support.a:rtc_clk.* *libesp_hw_support.a:sleep_mspi.* *libesp_hw_support.a:systimer.* *libesp_libc.a:abort.* *libesp_libc.a:assert.* *libesp_libc.a:heap.* *libesp_libc.a:memcmp.* *libesp_libc.a:memcpy.* *libesp_libc.a:memmove.* *libesp_libc.a:stdatomic.* *libesp_libc.a:strcmp.* *libesp_libc.a:strcpy.* *libesp_libc.a:strncmp.* *libesp_libc.a:strncpy.* *libesp_mm.a:esp_cache_msync.* *libesp_mm.a:esp_cache_utils.* *libesp_rom.a:esp_rom_cache_writeback_esp32p4.* *libesp_rom.a:esp_rom_print.* *libesp_rom.a:esp_rom_spiflash.* *libesp_rom.a:esp_rom_sys.* *libesp_rom.a:esp_rom_systimer.* *libesp_system.a:esp_err.* *libesp_system.a:image_process.* *libesp_system.a:reset_reason.* *libesp_system.a:system_internal.* *libesp_system.a:ubsan.* *libgcc.a:_divsf3.* *libgcc.a:save-restore.* *libhal.a:cache_hal.* *libhal.a:mmu_hal.* *libheap.a:multi_heap.* *libheap.a:tlsf.* *liblog.a:log.* *liblog.a:log_format_text.* *liblog.a:log_lock.* *liblog.a:log_print.* *liblog.a:log_timestamp_common.* *liblog.a:util.* *libsoc.a:lldesc.* *libspi_flash.a:flash_brownout_hook.* *libspi_flash.a:memspi_host_driver.* *libspi_flash.a:spi_flash_chip_boya.* *libspi_flash.a:spi_flash_chip_gd.* *libspi_flash.a:spi_flash_chip_generic.* *libspi_flash.a:spi_flash_chip_issi.* *libspi_flash.a:spi_flash_chip_mxic.* *libspi_flash.a:spi_flash_chip_th.* *libspi_flash.a:spi_flash_chip_winbond.* *libspi_flash.a:spi_flash_hpm_enable.* *libspi_flash.a:spi_flash_os_func_app.* *libspi_flash.a:spi_flash_wrap.*) .srodata EXCLUDE_FILE(*libgcov.a *libclang_rt.builtins.a:_divsf3.* *libclang_rt.builtins.a:restore.* *libclang_rt.builtins.a:save.* *libesp_driver_dma.a:dma2d.* *libesp_hal_mspi.a:spi_flash_encrypt_hal_iram.* *libesp_hal_mspi.a:spi_flash_hal_gpspi.* *libesp_hal_mspi.a:spi_flash_hal_iram.* *libesp_hal_pmu.a:pmu_hal.* *libesp_hal_wdt.a:rom_patch.* *libesp_hw_support.a:clk_utils.* *libesp_hw_support.a:cpu.* *libesp_hw_support.a:esp_clk_tree.* *libesp_hw_support.a:esp_memory_utils.* *libesp_hw_support.a:mspi_timing_by_dqs.* *libesp_hw_support.a:mspi_timing_by_flash_delay.* *libesp_hw_support.a:mspi_timing_config.* *libesp_hw_support.a:mspi_timing_tuning.* *libesp_hw_support.a:pmu_pvt.* *libesp_hw_support.a:pmu_sleep.* *libesp_hw_support.a:rtc_clk.* *libesp_hw_support.a:sleep_mspi.* *libesp_hw_support.a:systimer.* *libesp_libc.a:abort.* *libesp_libc.a:assert.* *libesp_libc.a:heap.* *libesp_libc.a:memcmp.* *libesp_libc.a:memcpy.* *libesp_libc.a:memmove.* *libesp_libc.a:stdatomic.* *libesp_libc.a:strcmp.* *libesp_libc.a:strcpy.* *libesp_libc.a:strncmp.* *libesp_libc.a:strncpy.* *libesp_mm.a:esp_cache_msync.* *libesp_mm.a:esp_cache_utils.* *libesp_rom.a:esp_rom_cache_writeback_esp32p4.* *libesp_rom.a:esp_rom_print.* *libesp_rom.a:esp_rom_spiflash.* *libesp_rom.a:esp_rom_sys.* *libesp_rom.a:esp_rom_systimer.* *libesp_system.a:esp_err.* *libesp_system.a:image_process.* *libesp_system.a:reset_reason.* *libesp_system.a:system_internal.* *libesp_system.a:ubsan.* *libgcc.a:_divsf3.* *libgcc.a:save-restore.* *libhal.a:cache_hal.* *libhal.a:mmu_hal.* *libheap.a:multi_heap.* *libheap.a:tlsf.* *liblog.a:log.* *liblog.a:log_format_text.* *liblog.a:log_lock.* *liblog.a:log_print.* *liblog.a:log_timestamp_common.* *liblog.a:util.* *libsoc.a:lldesc.* *libspi_flash.a:flash_brownout_hook.* *libspi_flash.a:memspi_host_driver.* *libspi_flash.a:spi_flash_chip_boya.* *libspi_flash.a:spi_flash_chip_gd.* *libspi_flash.a:spi_flash_chip_generic.* *libspi_flash.a:spi_flash_chip_issi.* *libspi_flash.a:spi_flash_chip_mxic.* *libspi_flash.a:spi_flash_chip_th.* *libspi_flash.a:spi_flash_chip_winbond.* *libspi_flash.a:spi_flash_hpm_enable.* *libspi_flash.a:spi_flash_os_func_app.* *libspi_flash.a:spi_flash_wrap.*) .srodata.*)
 *libesp_driver_dma.a:dma2d.*(.rodata .rodata.__FUNCTION__.1 .rodata.__FUNCTION__.10 .rodata.__FUNCTION__.11 .rodata.__FUNCTION__.12 .rodata.__FUNCTION__.14 .rodata.__FUNCTION__.15 .rodata.__FUNCTION__.16 .rodata.__FUNCTION__.17 .rodata.__FUNCTION__.2 .rodata.__FUNCTION__.20 .rodata.__FUNCTION__.22 .rodata.__FUNCTION__.25 .rodata.__FUNCTION__.3 .rodata.__FUNCTION__.4 .rodata.__FUNCTION__.7 .rodata.__FUNCTION__.8 .rodata.__FUNCTION__.9 .rodata.__func__.0 .rodata.__func__.13 .rodata.__func__.18 .rodata.__func__.19 .rodata.__func__.21 .rodata.__func__.23 .rodata.__func__.24 .rodata.dma2d_acquire_pool.str1.4 .rodata.dma2d_configure_color_space_conversion.str1.4 .rodata.dma2d_connect.str1.4 .rodata.dma2d_enqueue.str1.4 .rodata.dma2d_force_end.str1.4 .rodata.dma2d_register_tx_event_callbacks.str1.4 .rodata.dma2d_release_pool.str1.4 .rodata.dma2d_set_transfer_ability.str1.4 .rodata.dma2d_start.str1.4)
 *libesp_hw_support.a:cpu.*(.rodata.__func__.0 .rodata.__func__.1 .rodata.__func__.2)
 *libesp_hw_support.a:esp_clk_tree.*(.rodata.__FUNCTION__.0 .rodata.__FUNCTION__.1 .rodata.esp_clk_tree_src_get_freq_hz.str1.4 .rodata.esp_clk_tree_src_set_freq_hz.str1.4)
 *libesp_system.a:reset_reason.*(.rodata.__func__.0)
 *libesp_system.a:system_internal.*(.rodata.__func__.0)
 *libheap.a:multi_heap.*(.rodata.__func__.0 .rodata.__func__.1 .rodata.__func__.2 .rodata.__func__.3 .rodata.__func__.4 .rodata.__func__.5 .rodata.__func__.6 .rodata.__func__.7 .rodata.__func__.8 .rodata.multi_heap_dump.str1.4 .rodata.multi_heap_dump_tlsf.str1.4 .rodata.multi_heap_find_containing_block_impl.str1.4 .rodata.multi_heap_register_impl.str1.4)
 *libheap.a:tlsf.*(.rodata.__func__.0 .rodata.__func__.1 .rodata.__func__.10 .rodata.__func__.11 .rodata.__func__.12 .rodata.__func__.13 .rodata.__func__.14 .rodata.__func__.15 .rodata.__func__.16 .rodata.__func__.17 .rodata.__func__.19 .rodata.__func__.2 .rodata.__func__.20 .rodata.__func__.3 .rodata.__func__.5 .rodata.__func__.6 .rodata.__func__.7 .rodata.__func__.8 .rodata.__func__.9 .rodata.control_construct.str1.4 .rodata.default_walker.str1.4 .rodata.tlsf_add_pool.str1.4 .rodata.tlsf_check.str1.4 .rodata.tlsf_create.str1.4 .rodata.tlsf_remove_pool.str1.4)
 *libspi_flash.a:spi_flash_os_func_app.*(.rodata.__func__.0 .rodata.esp_flash_spi23_default_os_functions)
 mutable[flash_rodata]
    *(.got .got.plt) /* TODO: GCC-439 */
    *(.irom1.text) /* catch stray ICACHE_RODATA_ATTR */
    *(.gnu.linkonce.r.*)
    *(.rodata1)
    *(.gcc_except_table .gcc_except_table.*)
    *(.gnu.linkonce.e.*)
    . = ALIGN(ALIGNOF(.flash.init_array));
  } > flash_rodata_seg
  ASSERT((ADDR(.flash.init_array) == ADDR(.flash.rodata) + SIZEOF(.flash.rodata)), "The gap between .flash.rodata and .flash.init_array must not exist to produce the final bin image.")
  .flash.init_array :
  {
    /**
     * C++ constructor tables.
     *
     * Excluding crtbegin.o/crtend.o since IDF doesn't use the toolchain crt.
     */
    
 . = ALIGN(4); 
 __preinit_array_start = ABSOLUTE(.);
    
 . = ALIGN(4); 
 __bothinit_array_start = ABSOLUTE(.);
    KEEP (*(.preinit_array))
    __preinit_array_end = ABSOLUTE(.);
    
 . = ALIGN(4); 
 __init_array_start = ABSOLUTE(.);
    KEEP (*(SORT_BY_INIT_PRIORITY(EXCLUDE_FILE (*crtend.* *crtbegin.*) .init_array.*)))
    KEEP (*(EXCLUDE_FILE (*crtend.* *crtbegin.*) .init_array))
    __init_array_end = ABSOLUTE(.);
    __bothinit_array_end = ABSOLUTE(.);
    /* Addresses of memory regions reserved via SOC_RESERVE_MEMORY_REGION() */
    
 . = ALIGN(4); 
 soc_reserved_memory_region_start = ABSOLUTE(.);
    KEEP (*(.reserved_memory_address))
    soc_reserved_memory_region_end = ABSOLUTE(.);
    /* System init functions registered via ESP_SYSTEM_INIT_FN */
    
 . = ALIGN(4); 
 _esp_system_init_fn_array_start = ABSOLUTE(.);
    KEEP (*(SORT_BY_INIT_PRIORITY(.esp_system_init_fn.*)))
    _esp_system_init_fn_array_end = ABSOLUTE(.);
    _rodata_end = ABSOLUTE(.);
    . = ALIGN(ALIGNOF(.flash.tdata));
  } > flash_rodata_seg
  ASSERT((ADDR(.flash.tdata) == ADDR(.flash.init_array) + SIZEOF(.flash.init_array)), "The gap between .flash.init_array and .flash.tdata must not exist to produce the final bin image.")
  .flash.tdata :
  {
    /**
     * IMPORTANT: Keep tdata and tbss sections contiguous (no gaps between them).
     * The TLS runtime code calculates offsets assuming these sections are
     * adjacent. Gaps would cause incorrect address calculations, leading
     * to accessing wrong memory.
     */
    /* Thread-local data sections */
    _thread_local_data_start = ABSOLUTE(.);
    _picolibc_reent_stub_start = ABSOLUTE(.);
    KEEP(*(.tdata.errno))
    /* Reproduce the public fields from struct _reent */
    KEEP(*(.tdata.tls_stdin))
    KEEP(*(.tdata.tls_stdout))
    KEEP(*(.tdata.tls_stderr))
    _picolibc_reent_stub_end = ABSOLUTE(.);
    *(.tdata .tdata.* .gnu.linkonce.td.*)
    . = ALIGN(ALIGNOF(.flash.tbss));
    _thread_local_data_end = ABSOLUTE(.);
  } > flash_rodata_seg
  ASSERT((ADDR(.flash.tbss) == ADDR(.flash.tdata) + SIZEOF(.flash.tdata)), "The gap between .flash.tdata and .flash.tbss must not exist to produce the final bin image.")
  ASSERT((_picolibc_reent_stub_end - _picolibc_reent_stub_start) == 16, "Newlib _reent stub have wrong size")
  .flash.tbss (NOLOAD) :
  {
    /* Thread-local BSS sections */
    _thread_local_bss_start = ABSOLUTE(.);
    *(.tbss .tbss.* .gnu.linkonce.tb.*)
    *(.tcommon .tcommon.*)
    _thread_local_bss_end = ABSOLUTE(.);
  } > flash_rodata_seg
  ASSERT(_thread_local_data_end == _thread_local_bss_start,
         "tdata and tbss must be contiguous.")
  /**
   * This section contains all the rodata that is not used at runtime,
   * helping to avoid an increase in binary size.
   */
  .flash.rodata_noload (NOLOAD) :
  {
    /**
     * This symbol marks the end of flash.rodata. It can be utilized by the MMU
     * driver to maintain the virtual address.
     * NOLOAD rodata may not be included in this section.
     */
    _rodata_reserved_end = .;
    
 mutable[rodata_noload]
  } > flash_rodata_seg
  /**
   * If rodata default segment is placed in `flash_rodata_seg`, then flash's first
   * rodata section must also be first in the segment.
   */
  ASSERT(_flash_rodata_dummy_start == ORIGIN(flash_rodata_seg),
         ".flash_rodata_dummy section must be placed at the beginning of the rodata segment.")
/*
 * SPDX-FileCopyrightText: 2021-2024 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: Apache-2.0
 */
/* CPU instruction prefetch padding size for flash mmap scenario */
/*
 * PMP region granularity size
 * Software may determine the PMP granularity by writing zero to pmp0cfg, then writing all ones
 * to pmpaddr0, then reading back pmpaddr0. If G is the index of the least-significant bit set,
 * the PMP granularity is 2^G+2 bytes.
 */
/* CPU instruction prefetch padding size for memory protection scenario */
/* Memory alignment size for PMS */
    /* rtc timer data (s_rtc_timer_retain_mem, see esp_clk.c files). For rtc_timer_data_in_rtc_mem section. */
  .dram0.heap_start (NOLOAD) :
  {
    
 . = ALIGN(16); 
 _heap_start = ABSOLUTE(.);
  } > dram_seg
  ASSERT(((_heap_start - ORIGIN(dram_seg)) <= LENGTH(dram_seg)),
          "DRAM segment data does not fit.")
/*
 * SPDX-FileCopyrightText: 2021-2024 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: Apache-2.0
 */
/* CPU instruction prefetch padding size for flash mmap scenario */
/*
 * PMP region granularity size
 * Software may determine the PMP granularity by writing zero to pmp0cfg, then writing all ones
 * to pmpaddr0, then reading back pmpaddr0. If G is the index of the least-significant bit set,
 * the PMP granularity is 2^G+2 bytes.
 */
/* CPU instruction prefetch padding size for memory protection scenario */
/* Memory alignment size for PMS */
    /* rtc timer data (s_rtc_timer_retain_mem, see esp_clk.c files). For rtc_timer_data_in_rtc_mem section. */
  /**
   * This section is not included in the binary image; it is only present in the ELF file.
   * It is used to keep certain symbols in the ELF file.
   */
  .noload 0 (INFO) :
  {
    /* Reserve first 4 bytes as zero for vars pointed to NULL */
    . = 0;
    LONG(0);
    _noload_keep_in_elf_start = ABSOLUTE(.);
    
 mutable[noload_keep_in_elf]
    KEEP(*(.noload_keep_in_elf .noload_keep_in_elf.*))
    _noload_keep_in_elf_end = ABSOLUTE(.);
  }
  /* DWARF 1 */
  .debug 0 : { *(.debug) }
  .line 0 : { *(.line) }
  /* GNU DWARF 1 extensions */
  .debug_srcinfo 0 : { *(.debug_srcinfo) }
  .debug_sfnames 0 : { *(.debug_sfnames) }
  /* DWARF 1.1 and DWARF 2 */
  .debug_aranges 0 : { *(.debug_aranges) }
  .debug_pubnames 0 : { *(.debug_pubnames) }
  /* DWARF 2 */
  .debug_info 0 : { *(.debug_info .gnu.linkonce.wi.*) }
  .debug_abbrev 0 : { *(.debug_abbrev) }
  .debug_line 0 : { *(.debug_line) }
  .debug_frame 0 : { *(.debug_frame) }
  .debug_str 0 : { *(.debug_str) }
  .debug_loc 0 : { *(.debug_loc) }
  .debug_macinfo 0 : { *(.debug_macinfo) }
  .debug_pubtypes 0 : { *(.debug_pubtypes) }
  /* DWARF 3 */
  .debug_ranges 0 : { *(.debug_ranges) }
  /* SGI/MIPS DWARF 2 extensions */
  .debug_weaknames 0 : { *(.debug_weaknames) }
  .debug_funcnames 0 : { *(.debug_funcnames) }
  .debug_typenames 0 : { *(.debug_typenames) }
  .debug_varnames 0 : { *(.debug_varnames) }
  /* GNU DWARF 2 extensions */
  .debug_gnu_pubnames 0 : { *(.debug_gnu_pubnames) }
  .debug_gnu_pubtypes 0 : { *(.debug_gnu_pubtypes) }
  /* DWARF 4 */
  .debug_types 0 : { *(.debug_types) }
  /* DWARF 5 */
  .debug_addr 0 : { *(.debug_addr) }
  .debug_line_str 0 : { *(.debug_line_str) }
  .debug_loclists 0 : { *(.debug_loclists) }
  .debug_macro 0 : { *(.debug_macro) }
  .debug_names 0 : { *(.debug_names) }
  .debug_rnglists 0 : { *(.debug_rnglists) }
  .debug_str_offsets 0 : { *(.debug_str_offsets) }
  /**
   * Miscellaneous sections
   */
  .comment 0 : { *(.comment) }
  .note.GNU-stack 0 : { *(.note.GNU-stack) }
  .riscv.attributes 0 : { *(.riscv.attributes) }
/**
 * .xt.prop and .xt.lit sections will be used by the debugger and disassembler
 * to get more information about raw data present in the code.
 * Indeed, it may be required to add some padding at some points in the code
 * in order to align a branch/jump destination on a particular bound.
 * Padding these instructions will generate null bytes that shall be
 * interpreted as data, and not code by the debugger or disassembler.
 * This section will only be present in the ELF file, not in the final binary
 * For more details, check GCC-212
 */
  .xtensa.info 0 : { *(.xtensa.info) }
  .xt.prop 0 : { *(.xt.prop .xt.prop.* .gnu.linkonce.prop.*) }
  .xt.lit 0 : { *(.xt.lit .xt.lit.* .gnu.linkonce.p.*) }
/*
 * SPDX-FileCopyrightText: 2021-2024 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: Apache-2.0
 */
/* CPU instruction prefetch padding size for flash mmap scenario */
/*
 * PMP region granularity size
 * Software may determine the PMP granularity by writing zero to pmp0cfg, then writing all ones
 * to pmpaddr0, then reading back pmpaddr0. If G is the index of the least-significant bit set,
 * the PMP granularity is 2^G+2 bytes.
 */
/* CPU instruction prefetch padding size for memory protection scenario */
/* Memory alignment size for PMS */
    /* rtc timer data (s_rtc_timer_retain_mem, see esp_clk.c files). For rtc_timer_data_in_rtc_mem section. */
  /DISCARD/ :
  {
   /**
    * Discarding .rela.* sections results in the following mapping:
    * .rela.text.* -> .text.*
    * .rela.data.* -> .data.*
    * And so forth...
    */
   *(.rela.*)
   *(.fini)
   *(.eh_frame_hdr)
   *(.eh_frame)
  }
}
