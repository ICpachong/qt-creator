/****************************************************************************
**
** Copyright (C) 2015 The Qt Company Ltd.
** Contact: http://www.qt.io/licensing
**
** This file is part of Qt Creator.
**
** Commercial License Usage
** Licensees holding valid commercial Qt licenses may use this file in
** accordance with the commercial license agreement provided with the
** Software or, alternatively, in accordance with the terms contained in
** a written agreement between you and The Qt Company.  For licensing terms and
** conditions see http://www.qt.io/terms-conditions.  For further information
** use the contact form at http://www.qt.io/contact-us.
**
** GNU Lesser General Public License Usage
** Alternatively, this file may be used under the terms of the GNU Lesser
** General Public License version 2.1 or version 3 as published by the Free
** Software Foundation and appearing in the file LICENSE.LGPLv21 and
** LICENSE.LGPLv3 included in the packaging of this file.  Please review the
** following information to ensure the GNU Lesser General Public License
** requirements will be met: https://www.gnu.org/licenses/lgpl.html and
** http://www.gnu.org/licenses/old-licenses/lgpl-2.1.html.
**
** In addition, as a special exception, The Qt Company gives you certain additional
** rights.  These rights are described in The Qt Company LGPL Exception
** version 1.1, included in the file LGPL_EXCEPTION.txt in this package.
**
****************************************************************************/

#ifndef UPDATEINFOPLUGIN_H
#define UPDATEINFOPLUGIN_H

#include <extensionsystem/iplugin.h>

#include <QTime>
#include <QDomDocument>

namespace UpdateInfo {

namespace Constants {
    const char FILTER_OPTIONS_PAGE[] = QT_TRANSLATE_NOOP("Update", "Update");
} // namespace Constants

namespace Internal {

class SettingsPage;
class UpdateInfoPluginPrivate;

class UpdateInfoPlugin : public ExtensionSystem::IPlugin
{
    Q_OBJECT
    Q_PLUGIN_METADATA(IID "org.qt-project.Qt.QtCreatorPlugin" FILE "UpdateInfo.json")

public:
    UpdateInfoPlugin();
    virtual ~UpdateInfoPlugin();

    bool delayedInitialize();
    void extensionsInitialized();
    bool initialize(const QStringList &arguments, QString *errorMessage);

    void loadSettings();
    void saveSettings();

    QTime scheduledUpdateTime() const;
    void setScheduledUpdateTime(const QTime &time);

protected:
    void timerEvent(QTimerEvent *event);

private slots:
    void parseUpdates();
    void startUpdaterUiApplication();

private:
    QDomDocument update();
    template <typename T> void settingsHelper(T *settings);

private:
    UpdateInfoPluginPrivate *d;
};

} // namespace Internal
} // namespace UpdateInfo

#endif // UPDATEINFOPLUGIN_H