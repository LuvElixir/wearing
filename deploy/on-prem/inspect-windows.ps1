#requires -Version 5.1
<#
.SYNOPSIS
Read-only, local Windows inventory for a possible Pajio VM host.
.DESCRIPTION
Emits a deliberately allowlisted JSON summary to stdout. No automatic file
write, network request, benchmark, install, system change or remote CIM session.
Does not emit computer/account names, serials, MAC/IP addresses, volume labels,
file paths, credentials, recovery keys or Wi-Fi profiles. Query errors are fixed
status codes, never raw exception text. Run with -NoProfile -File, not dot-source.
Storage counters are optional and do not prove that a disk is healthy.
.PARAMETER ExpectedComputerName
Optional local guard for a known remote target. A mismatch stops before hardware
queries and does not print the actual computer name. This is not SSH host-key
verification: the caller must verify its transport separately.
#>
[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9-]{0,62}$')]
    [string]$ExpectedComputerName
)

$ErrorActionPreference = 'Stop'
$WarningPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'
$VerbosePreference = 'SilentlyContinue'
$DebugPreference = 'SilentlyContinue'
$InformationPreference = 'SilentlyContinue'

if ($env:OS -ne 'Windows_NT') {
    [pscustomobject]@{ schema = 1; status = 'unsupported_platform'; read_only = $true } |
        ConvertTo-Json -Depth 3
    exit 2
}
if ($ExpectedComputerName -and -not [string]::Equals(
        $ExpectedComputerName, $env:COMPUTERNAME,
        [System.StringComparison]::OrdinalIgnoreCase)) {
    [pscustomobject]@{ schema = 1; status = 'host_mismatch'; read_only = $true } |
        ConvertTo-Json -Depth 3
    exit 2
}

function Read-PajioProperty {
    param([object]$Item, [string]$Name)
    if ($null -eq $Item) { return $null }
    $property = $Item.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function ConvertTo-PajioNumber {
    param([object]$Value)
    if ($null -eq $Value -or [string]::IsNullOrWhiteSpace([string]$Value)) { return $null }
    try {
        $number = [double]$Value
        if ([double]::IsNaN($number) -or [double]::IsInfinity($number) -or $number -lt 0) {
            return $null
        }
        return $number
    } catch { return $null }
}

function ConvertTo-PajioGiB {
    param([object]$Bytes)
    $number = ConvertTo-PajioNumber $Bytes
    if ($null -eq $number) { return $null }
    return [math]::Round($number / 1GB, 2)
}

function ConvertTo-PajioBool {
    param([object]$Value)
    if ($Value -is [bool]) { return $Value }
    return $null
}

function ConvertTo-PajioLabel {
    param([object]$Value, [string[]]$Allowed)
    $label = [string]$Value
    if ($Allowed -contains $label) { return $label }
    return 'unknown'
}

function Invoke-PajioProbe {
    param([scriptblock]$Read)
    try {
        $rows = @(& $Read)
        return [pscustomobject]@{ status = 'read'; data = $rows }
    } catch {
        # Do not emit $_, ErrorRecord, provider objects or provider paths.
        return [pscustomobject]@{ status = 'unavailable'; data = @() }
    }
}

$operatingSystem = Invoke-PajioProbe {
    Get-CimInstance -ClassName Win32_OperatingSystem -Property Version, BuildNumber,
        OSArchitecture, ProductType, FreePhysicalMemory -OperationTimeoutSec 15 |
        Select-Object -First 1 | ForEach-Object {
            [pscustomobject]@{
                version = if ($_.Version -match '^\d+(\.\d+){1,3}$') { [string]$_.Version } else { $null }
                build = ConvertTo-PajioNumber $_.BuildNumber
                architecture = ConvertTo-PajioLabel $_.OSArchitecture @('32-bit', '64-bit', 'ARM 64-bit')
                product_type = ConvertTo-PajioNumber $_.ProductType
                available_memory_gib = if ($null -ne $_.FreePhysicalMemory) {
                    ConvertTo-PajioGiB ([double]$_.FreePhysicalMemory * 1KB)
                } else { $null }
            }
        }
}

$system = Invoke-PajioProbe {
    Get-CimInstance -ClassName Win32_ComputerSystem -Property TotalPhysicalMemory,
        HypervisorPresent -OperationTimeoutSec 15 | Select-Object -First 1 |
        ForEach-Object {
            [pscustomobject]@{
                installed_memory_gib = ConvertTo-PajioGiB $_.TotalPhysicalMemory
                hypervisor_present = ConvertTo-PajioBool $_.HypervisorPresent
            }
        }
}

$processors = Invoke-PajioProbe {
    $cpuIndex = 0
    Get-CimInstance -ClassName Win32_Processor -Property Name, Architecture,
        AddressWidth, NumberOfCores, NumberOfLogicalProcessors, MaxClockSpeed,
        VirtualizationFirmwareEnabled, VMMonitorModeExtensions,
        SecondLevelAddressTranslationExtensions -OperationTimeoutSec 15 |
        Select-Object -First 64 | ForEach-Object {
            $cpuIndex++
            # CPU Name is the hardware model string, not the machine name or ID.
            $cpuModel = ([string]$_.Name -replace '[\x00-\x1f\x7f]', '').Trim()
            if ($cpuModel.Length -gt 120) { $cpuModel = $cpuModel.Substring(0, 120) }
            [pscustomobject]@{
                cpu = $cpuIndex
                model = $cpuModel
                architecture_code = ConvertTo-PajioNumber $_.Architecture
                address_width = ConvertTo-PajioNumber $_.AddressWidth
                physical_cores = ConvertTo-PajioNumber $_.NumberOfCores
                logical_processors = ConvertTo-PajioNumber $_.NumberOfLogicalProcessors
                maximum_clock_mhz = ConvertTo-PajioNumber $_.MaxClockSpeed
                virtualization_firmware_enabled = ConvertTo-PajioBool $_.VirtualizationFirmwareEnabled
                vm_monitor_extensions = ConvertTo-PajioBool $_.VMMonitorModeExtensions
                second_level_translation = ConvertTo-PajioBool $_.SecondLevelAddressTranslationExtensions
            }
        }
}

$memoryModules = Invoke-PajioProbe {
    $memoryIndex = 0
    Get-CimInstance -ClassName Win32_PhysicalMemory -Property Capacity, Speed,
        ConfiguredClockSpeed, DataWidth, TotalWidth -OperationTimeoutSec 15 |
        Select-Object -First 128 | ForEach-Object {
            $memoryIndex++
            [pscustomobject]@{
                module = $memoryIndex
                size_gib = ConvertTo-PajioGiB $_.Capacity
                reported_speed = ConvertTo-PajioNumber $_.Speed
                configured_clock_mhz = ConvertTo-PajioNumber $_.ConfiguredClockSpeed
                data_width_bits = ConvertTo-PajioNumber $_.DataWidth
                total_width_bits = ConvertTo-PajioNumber $_.TotalWidth
            }
        }
}

$disks = Invoke-PajioProbe {
    Get-CimInstance -ClassName Win32_DiskDrive -Property Index, Size, InterfaceType,
        Status, Partitions -OperationTimeoutSec 15 | Sort-Object Index |
        Select-Object -First 128 | ForEach-Object {
            [pscustomobject]@{
                local_disk_number = ConvertTo-PajioNumber $_.Index
                size_gib = ConvertTo-PajioGiB $_.Size
                interface = ConvertTo-PajioLabel $_.InterfaceType @('SCSI', 'HDC', 'IDE', 'USB', '1394')
                status_reported = ConvertTo-PajioLabel $_.Status @('OK', 'Error', 'Degraded', 'Unknown', 'Pred Fail', 'Starting', 'Stopping', 'Service', 'Stressed', 'NonRecover', 'No Contact', 'Lost Comm')
                partition_count = ConvertTo-PajioNumber $_.Partitions
            }
        }
}

$volumes = Invoke-PajioProbe {
    $volumeIndex = 0
    # Local fixed volumes only. Do not read labels, mount paths or file contents.
    Get-CimInstance -ClassName Win32_LogicalDisk -Filter 'DriveType=3' -Property Size,
        FreeSpace, FileSystem -OperationTimeoutSec 15 | Select-Object -First 128 |
        ForEach-Object {
            $volumeIndex++
            [pscustomobject]@{
                report_volume = $volumeIndex
                size_gib = ConvertTo-PajioGiB $_.Size
                free_gib = ConvertTo-PajioGiB $_.FreeSpace
                filesystem = ConvertTo-PajioLabel $_.FileSystem @('NTFS', 'ReFS', 'FAT', 'FAT32', 'exFAT', 'RAW')
            }
        }
}

$networkLinks = Invoke-PajioProbe {
    $adapterIndex = 0
    Get-CimInstance -ClassName Win32_NetworkAdapter -Filter 'PhysicalAdapter=True' -Property Speed,
        NetEnabled, AdapterTypeID -OperationTimeoutSec 15 |
        Select-Object -First 32 | ForEach-Object {
            $adapterIndex++
            $linkSpeed = ConvertTo-PajioNumber $_.Speed
            [pscustomobject]@{
                report_adapter = $adapterIndex
                enabled = ConvertTo-PajioBool $_.NetEnabled
                adapter_type_code = ConvertTo-PajioNumber $_.AdapterTypeID
                reported_link_mbps = if ($null -ne $linkSpeed) { [math]::Round($linkSpeed / 1000000, 2) } else { $null }
            }
        }
}

# Storage cmdlets can operate cluster-wide in a Failover Cluster. Skip them when
# ClusSvc is installed, or when the local service check itself is inconclusive.
$clusterCheck = Invoke-PajioProbe {
    Get-CimInstance -ClassName Win32_Service -Filter "Name='ClusSvc'" -Property State -OperationTimeoutSec 15 |
        ForEach-Object { [pscustomobject]@{ installed = $true } }
}
$storage = [pscustomobject]@{ status = 'skipped_cluster_or_unknown'; data = @() }
if ($clusterCheck.status -eq 'read' -and @($clusterCheck.data).Count -eq 0) {
    $storage = Invoke-PajioProbe {
        Get-Disk -ErrorAction Stop | Sort-Object Number | Select-Object -First 128 |
            ForEach-Object {
                $disk = $_
                $bus = ConvertTo-PajioLabel $disk.BusType @('Unknown', 'SCSI', 'ATAPI', 'ATA', '1394', 'SSA', 'Fibre Channel', 'USB', 'RAID', 'iSCSI', 'SAS', 'SATA', 'SD', 'MMC', 'Virtual', 'File Backed Virtual', 'Storage Spaces', 'NVMe', 'SCM', 'UFS')
                $counters = [pscustomobject]@{ status = 'skipped_nonlocal_or_unsupported'; data = @() }
                # Do not request counters from network / virtual / pooled disks.
                if (@('ATA', 'ATAPI', 'USB', 'SATA', 'NVMe', 'SD', 'MMC', 'UFS') -contains $bus) {
                    $counters = Invoke-PajioProbe {
                        Get-StorageReliabilityCounter -Disk $disk -ErrorAction Stop |
                            Select-Object -First 1 | ForEach-Object {
                                [pscustomobject]@{
                                    temperature_c = ConvertTo-PajioNumber (Read-PajioProperty $_ 'Temperature')
                                    power_on_hours = ConvertTo-PajioNumber (Read-PajioProperty $_ 'PowerOnHours')
                                    wear_reported = ConvertTo-PajioNumber (Read-PajioProperty $_ 'Wear')
                                    read_errors_uncorrected = ConvertTo-PajioNumber (Read-PajioProperty $_ 'ReadErrorsUncorrected')
                                    write_errors_uncorrected = ConvertTo-PajioNumber (Read-PajioProperty $_ 'WriteErrorsUncorrected')
                                }
                            }
                    }
                }
                [pscustomobject]@{
                    local_disk_number = ConvertTo-PajioNumber $disk.Number
                    size_gib = ConvertTo-PajioGiB $disk.Size
                    bus = $bus
                    partition_style = ConvertTo-PajioLabel $disk.PartitionStyle @('Unknown', 'RAW', 'MBR', 'GPT')
                    health_reported = ConvertTo-PajioLabel $disk.HealthStatus @('Healthy', 'Warning', 'Unhealthy', 'Unknown')
                    is_boot = ConvertTo-PajioBool $disk.IsBoot
                    is_system = ConvertTo-PajioBool $disk.IsSystem
                    is_offline = ConvertTo-PajioBool $disk.IsOffline
                    is_read_only = ConvertTo-PajioBool $disk.IsReadOnly
                    reliability = $counters
                }
            }
    }
}

$report = [ordered]@{
    schema = 1
    status = 'inspection_only'
    captured_at_utc = [DateTime]::UtcNow.ToString('o')
    read_only = $true
    expected_host_guard = if ($ExpectedComputerName) { 'matched' } else { 'not_requested' }
    powershell_version = $PSVersionTable.PSVersion.ToString()
    windows = $operatingSystem
    system = $system
    processors = $processors
    memory_modules = $memoryModules
    disks = $disks
    fixed_volumes = $volumes
    storage_details = $storage
    physical_network_links = $networkLinks
    assessment = [ordered]@{
        deployment_ready = 'not_assessed'
        tenant_capacity = 'not_assessed'
        internet_upload_mbps = $null
        manual_follow_up = @(
            'Confirm the intended physical host and actual disks locally before reinstalling.',
            'Verify external backup restoration; never share passwords or recovery keys.',
            'A Windows virtualization flag is preliminary; validate KVM after booting the chosen Linux host.',
            'An existing hypervisor may affect Windows virtualization reporting. False or null is not a final hardware verdict.',
            'Disk status and counters are reported values, not a surface test or a guarantee of health.',
            'An empty or unavailable section is unknown, never a passing check.',
            'NIC link speed is not Internet upload throughput.',
            'Measure upload manually only with company network authorization and a chosen test endpoint; use synthetic data.',
            'Record repeated upload, latency, jitter, packet loss and test times; this script does not run any network test.',
            'Check cooling, UPS runtime, power-loss recovery, management-network isolation and off-site restore separately.'
        )
    }
}
$report | ConvertTo-Json -Depth 10
