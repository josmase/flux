# netboot.xyz

Network boot utility for PXE booting various operating systems and tools.

## Access

- **Web Interface**: https://netboot.${DOMAIN}
- **Assets Server**: https://netboot-assets.${DOMAIN}
- **TFTP**: Port 69 (UDP) on the service IP

## Configuration

The web interface at port 3000 provides configuration management for:
- Boot menu customization
- Local asset downloads
- Mirror configuration

## DHCP Configuration Required

netboot.xyz requires a DHCP server configured to point to this service. You'll need to configure your DHCP server with:

- **next-server**: IP address of the netbootxyz LoadBalancer service (${NETBOOT_IP})
- **boot-file-name**: Typically `netboot.xyz.kpxe` or similar depending on boot mode

### Example DHCP Configuration

For dnsmasq:
```
dhcp-boot=netboot.xyz.kpxe,netbootxyz,${NETBOOT_IP}
```

For ISC DHCP:
```
next-server ${NETBOOT_IP};
filename "netboot.xyz.kpxe";
```

## Local Mirror

To use local asset caching:
1. Access the web interface
2. Edit `local-vars.ipxe`
3. Set `live_endpoint` to `http://netboot-assets.${DOMAIN}` or the service IP
4. Use the web interface to download assets locally

## Storage

- **Config Volume**: 5Gi for configuration files
- **Assets Volume**: 50Gi for local boot asset caching (adjust as needed)

## Documentation

- [Official Documentation](https://netboot.xyz/docs/)
- [Docker Usage](https://netboot.xyz/docs/docker/usage)
