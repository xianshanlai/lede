include $(TOPDIR)/rules.mk

PKG_NAME:=openlist-cas
PKG_VERSION:=4.2.3.3
PKG_RELEASE:=1

PKG_SOURCE:=openlist-linux-musl-amd64.tar.gz
PKG_SOURCE_URL:=https://github.com/GitYuA/OpenList-CAS/releases/download/v$(PKG_VERSION)/
PKG_HASH:=219c4abb5105f73bcf1fdd97acde2562172b4a7389810da42848c09c5f509e1a
PKG_BUILD_DIR:=$(BUILD_DIR)/$(PKG_NAME)-$(PKG_VERSION)

PKG_LICENSE:=AGPL-3.0-only
PKG_LICENSE_FILES:=LICENSE
PKG_MAINTAINER:=xianshanlai

include $(INCLUDE_DIR)/package.mk

define Package/openlist-cas
  SECTION:=net
  CATEGORY:=Network
  SUBMENU:=Web Servers/Proxies
  TITLE:=OpenList with 189Cloud CAS restore and playback support
  URL:=https://github.com/GitYuA/OpenList-CAS
  DEPENDS:=@TARGET_x86_64 +ca-bundle +curl +lua +luci-lib-base +luci-lib-jsonc +luci-lib-nixio
endef

define Package/openlist-cas/description
  Non-official OpenList build with 189Cloud CAS restore and temporary playback support.
endef

define Package/openlist-cas/conffiles
/etc/openlist-cas
endef

define Build/Compile
endef

define Package/openlist-cas/install
	$(INSTALL_DIR) $(1)/usr/bin $(1)/usr/libexec $(1)/etc/init.d $(1)/etc/openlist-cas
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/openlist $(1)/usr/bin/openlist-cas
	$(INSTALL_BIN) ./files/openlist-cas.init $(1)/etc/init.d/openlist-cas
	$(INSTALL_BIN) ./files/openlist-cas-strm.lua $(1)/usr/libexec/openlist-cas-strm.lua
endef

$(eval $(call BuildPackage,openlist-cas))
